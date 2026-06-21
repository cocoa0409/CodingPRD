"""BOM line constraints, release gating, the supersession cascade, and uniqueness.

Covers queue-B corner instances on designator mismatch, no-approved-source release
gating, and BOM revision uniqueness, plus the queue-A depth-3 release cascade.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f

PE = TEST_USERS["process_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]


# ---------------------------------------------------------------------------
# BOM line designator validation
# ---------------------------------------------------------------------------

def test_designator_count_mismatch_rejected(api):
    """PRD §3.3: "a `qty_per_assembly` count of placements of that part per finished
    assembly, which must be greater than zero and must equal the number of reference
    designators supplied. If the placement count does not equal the length of the
    designator list, or a designator is duplicated within the bill of materials, the
    line is rejected with `ERR_DESIGNATOR_MISMATCH` (HTTP 422)."

    Design: Corner/validations/designator_count_mismatch_rejected
    """
    part = fx.create_part()
    bom = fx.create_draft_bom()
    payload = f.add_bom_line_payload(part["id"], ref_designators=["R1", "R2"],
                                     qty_per_assembly=3)
    validate_error(api.add_bom_line(bom["id"], payload, PE),
                   ApiErrorId.ERR_DESIGNATOR_MISMATCH.value)


# ---------------------------------------------------------------------------
# Release gating on approved source
# ---------------------------------------------------------------------------

def test_release_with_unsourced_part_rejected(api):
    """PRD §3.3: "A `ProcessEngineer` may release a bill of materials only while it is
    in `DRAFT`, only when it has at least one line, and only when every line's part
    has at least one approval record in `APPROVED` status. If some non-do-not-place
    line's part has no approved source, release is rejected with
    `ERR_NO_APPROVED_SOURCE` (HTTP 422)."

    Design: Corner/validations/bom_release_no_approved_source_rejected
    """
    part = fx.create_part()  # no AVL entry
    bom = fx.create_draft_bom()
    fx.add_line(bom["id"], part["id"], ref_designators=["R1"], qty_per_assembly=1)
    validate_error(api.release_bom(bom["id"], PE),
                   ApiErrorId.ERR_NO_APPROVED_SOURCE.value)
    fetched = validate_success(api.get_bom(bom["id"], PE))
    assert fetched["status"] == "DRAFT", fetched


# ---------------------------------------------------------------------------
# BOM revision uniqueness within product (queue A: resource_temporal_overlap)
# ---------------------------------------------------------------------------

def test_duplicate_revision_within_product_rejected(api):
    """PRD §3.3: "a `revision` label such as `A`, `B`, or `C` that must be unique
    within the product code".
    PRD §2.7: "a generic business-rule violation not covered by a more specific code
    (such as a non-positive received quantity) yields `ERR_VALIDATION` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/bom_revision_uniqueness_within_product_collision
    """
    first = get_success_data(api.create_bom(
        f.create_bom_payload(product_code="DUP-PROD", revision="A"), PE))
    dup = api.create_bom(f.create_bom_payload(product_code="DUP-PROD", revision="A"), PE)
    validate_error(dup, ApiErrorId.ERR_VALIDATION.value)
    assert first["revision"] == "A"


def test_same_revision_distinct_products_allowed(api):
    """PRD §3.3: "a `revision` label such as `A`, `B`, or `C` that must be unique
    within the product code".

    The uniqueness key is (product_code, revision), so the same revision under a
    different product_code is accepted — pinning the two-key scope of the constraint.

    Design: Difficulty/resource_temporal_overlap/bom_revision_uniqueness_within_product_collision
    """
    bom_a = get_success_data(api.create_bom(
        f.create_bom_payload(product_code="PROD-X", revision="A"), PE))
    bom_b = validate_success(api.create_bom(
        f.create_bom_payload(product_code="PROD-Y", revision="A"), PE),
        expected_status=201)
    assert bom_a["product_code"] != bom_b["product_code"]
    assert bom_b["revision"] == "A"


# ---------------------------------------------------------------------------
# Release supersession cascade (queue A: transitive_cascade depth 3)
# ---------------------------------------------------------------------------

def _build_superseding_pair(api):
    """Released rev A + a PLANNED work order on rev A + a DRAFT rev B that
    supersedes A and has a line on the same approved part. Returns (bom_a, bom_b, wo)."""
    part = fx.create_part(standard_cost_cents=30)
    fx.create_approved_avl(part["id"])  # approves the part for release
    product = f"CASCADE-{fx._n()}"
    bom_a = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1,
                                               product_code=product, revision="A")
    wo = fx.create_work_order(bom_a["id"], planned_qty=5)
    bom_b = fx.create_draft_bom(product_code=product, revision="B",
                                supersedes_bom_id=bom_a["id"])
    fx.add_line(bom_b["id"], part["id"], ref_designators=["R1"], qty_per_assembly=1)
    return bom_a, bom_b, wo


def test_release_obsoletes_superseded_revision(api):
    """PRD §3.3: "Release also drives a two-hop cascade onto the revision it
    supersedes: if `supersedes_bom_id` is not null and that prior bill of materials is
    currently `RELEASED`, the prior bill transitions from `RELEASED` to `OBSOLETE`".

    Design: Difficulty/transitive_cascade/bom_release_obsolete_cancel_depth_three_cascade
    """
    bom_a, bom_b, _wo = _build_superseding_pair(api)
    released_b = validate_success(api.release_bom(bom_b["id"], PE))
    assert released_b["status"] == "RELEASED", released_b
    fetched_a = validate_success(api.get_bom(bom_a["id"], PE))
    assert fetched_a["status"] == "OBSOLETE", fetched_a


def test_release_cancels_planned_workorder_on_obsoleted_bom(api):
    """PRD §3.3: "for that now-obsolete prior bill, every work order anchored to it
    that is still in `PLANNED` is set to `CANCELLED`, releasing any reservations those
    work orders held."

    Design: Difficulty/transitive_cascade/bom_release_obsolete_cancel_depth_three_cascade
    """
    _bom_a, bom_b, wo = _build_superseding_pair(api)
    get_success_data(api.release_bom(bom_b["id"], PE))
    fetched_wo = validate_success(api.get_work_order(wo["id"], PP))
    assert fetched_wo["status"] == "CANCELLED", fetched_wo
