"""Parallel design/aesthetic review: fork-join, capacity, cross-entity state
gates, pavement moratorium, slot conservation, and OCC on the structure.

Difficulty: non_linear_state_machine, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
Corner: calculations, state_machines, cross_cutting_complexity_layers.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    design_review_payload, aesthetic_review_payload,
    register_applicant, create_structure, create_segment, set_clock,
    open_application, add_node, submit, record_completeness,
    record_design_review, record_aesthetic_review,
    structure_version, fetch_node, fetch_structure,
    setup_under_review_single, setup_submitted_single,
    make_row_reviewer_headers, TEST_USERS, api_client,
)

ROW = TEST_USERS["row_reviewer_headers"]


# ─── Difficulty: node_parallel_design_aesthetic_join ──────────────────────
def test_design_pass_alone_leaves_node_in_review_in_historic_segment(api):
    """PRD §3.4: "A node joins to `APPROVED` only when its `design_review_status`
    is `PASS` and its `aesthetic_review_status` is either `PASS` or `WAIVED`."

    Design: Difficulty/non_linear_state_machine/node_parallel_design_aesthetic_join
    """
    ctx = setup_under_review_single(segment_kwargs={"in_historic_district": True})
    record_design_review(ctx["node"]["id"], ctx["structure"]["id"], outcome="PASS")
    node = fetch_node(ctx["node"]["id"])
    assert node["design_review_status"] == "PASS"
    assert node["aesthetic_review_status"] == "PENDING"
    assert node["status"] == "IN_REVIEW"


def test_node_joins_to_approved_when_both_dimensions_pass(api):
    """PRD §3.4: "A node joins to `APPROVED` only when its `design_review_status`
    is `PASS` and its `aesthetic_review_status` is either `PASS` or `WAIVED`."

    Design: Difficulty/non_linear_state_machine/node_parallel_design_aesthetic_join
    """
    ctx = setup_under_review_single(segment_kwargs={"in_historic_district": True})
    record_design_review(ctx["node"]["id"], ctx["structure"]["id"], outcome="PASS")
    record_aesthetic_review(ctx["node"]["id"], outcome="PASS")
    node = fetch_node(ctx["node"]["id"])
    assert node["design_review_status"] == "PASS"
    assert node["aesthetic_review_status"] == "PASS"
    assert node["status"] == "APPROVED"


# ─── Difficulty: structure_capacity_at_max_vs_over ────────────────────────
def _two_node_batch_under_review(max_collocations=1):
    applicant = register_applicant()
    ss = create_structure(max_collocations=max_collocations)
    seg = create_segment()
    set_clock("2026-06-01T00:00:00Z")
    app = open_application(applicant["id"])
    n1 = add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    n2 = add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    submit(app["id"], applicant["id"])
    record_completeness(app["id"], complete=True)
    return ss, n1, n2


def test_first_design_pass_at_capacity_one_reserves_slot(api):
    """PRD §3.4: "the sum of its `reserved_collocations` and `active_collocations`
    must be strictly less than its `max_collocations`, otherwise the pass is
    rejected with `ERR_STRUCTURE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/structure_capacity_at_max_vs_over
    """
    ss, n1, _ = _two_node_batch_under_review(max_collocations=1)
    record_design_review(n1["id"], ss["id"], outcome="PASS")
    structure = fetch_structure(ss["id"])
    assert structure["reserved_collocations"] == 1


def test_second_design_pass_over_capacity_rejected(api):
    """PRD §3.4: "the sum of its `reserved_collocations` and `active_collocations`
    must be strictly less than its `max_collocations`, otherwise the pass is
    rejected with `ERR_STRUCTURE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/structure_capacity_at_max_vs_over
    """
    ss, n1, n2 = _two_node_batch_under_review(max_collocations=1)
    record_design_review(n1["id"], ss["id"], outcome="PASS")
    cur_ver = structure_version(ss["id"])
    res = api.design_review(n2["id"], design_review_payload(cur_ver, outcome="PASS"), ROW)
    validate_error(res, "ERR_STRUCTURE_CAPACITY_EXCEEDED", 409)
    structure = fetch_structure(ss["id"])
    assert structure["reserved_collocations"] == 1


# ─── Difficulty: design_review_requires_application_under_review ──────────
def test_design_review_while_application_submitted_rejected(api):
    """PRD §3.4: "A design review is admissible only when the node is `IN_REVIEW`,
    its parent application is `UNDER_REVIEW`, and the referenced support structure
    is `ACTIVE`;"

    Design: Difficulty/cross_entity_state_dependency/design_review_requires_application_under_review
    """
    ctx = setup_submitted_single()  # SUBMITTED, completeness not yet performed
    ss_ver = structure_version(ctx["structure"]["id"])
    res = api.design_review(ctx["node"]["id"], design_review_payload(ss_ver, outcome="PASS"), ROW)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_design_review_admitted_once_application_under_review(api):
    """PRD §3.4: "A design review is admissible only when the node is `IN_REVIEW`,
    its parent application is `UNDER_REVIEW`, and the referenced support structure
    is `ACTIVE`;"

    Design: Difficulty/cross_entity_state_dependency/design_review_requires_application_under_review
    """
    ctx = setup_under_review_single()  # UNDER_REVIEW
    ss_ver = structure_version(ctx["structure"]["id"])
    res = api.design_review(ctx["node"]["id"], design_review_payload(ss_ver, outcome="PASS"), ROW)
    validate_success(res, 201)


# ─── Difficulty: design_review_requires_structure_active ──────────────────
def _under_review_referencing_retired_structure():
    applicant = register_applicant()
    ss = create_structure(max_collocations=2)
    # retire the structure (holds no slots yet)
    api_client.retire_support_structure(ss["id"], TEST_USERS["platform_admin_headers"])
    seg = create_segment()
    set_clock("2026-06-01T00:00:00Z")
    app = open_application(applicant["id"])
    node = add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    submit(app["id"], applicant["id"])
    record_completeness(app["id"], complete=True)
    return ss, node


def test_design_review_against_retired_structure_rejected(api):
    """PRD §3.4: "A design review is admissible only when the node is `IN_REVIEW`,
    its parent application is `UNDER_REVIEW`, and the referenced support structure
    is `ACTIVE`; a review against a retired structure is rejected with
    `ERR_STRUCTURE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/design_review_requires_structure_active
    """
    ss, node = _under_review_referencing_retired_structure()
    ss_ver = structure_version(ss["id"])
    res = api.design_review(node["id"], design_review_payload(ss_ver, outcome="PASS"), ROW)
    validate_error(res, "ERR_STRUCTURE_NOT_ACTIVE", 409)


def test_design_review_against_active_structure_admitted(api):
    """PRD §3.4: "A design review is admissible only when the node is `IN_REVIEW`,
    its parent application is `UNDER_REVIEW`, and the referenced support structure
    is `ACTIVE`; a review against a retired structure is rejected with
    `ERR_STRUCTURE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/design_review_requires_structure_active
    """
    ctx = setup_under_review_single()  # structure ACTIVE
    ss_ver = structure_version(ctx["structure"]["id"])
    res = api.design_review(ctx["node"]["id"], design_review_payload(ss_ver, outcome="PASS"), ROW)
    validate_success(res, 201)


# ─── Difficulty: new_pole_construction_within_pavement_moratorium ─────────
def _new_pole_under_review(construction_date):
    applicant = register_applicant()
    ss = create_structure(max_collocations=1, structure_type="NEW_POLE")
    seg = create_segment(
        last_paved_at="2026-01-01T00:00:00Z", moratorium_months=36, in_historic_district=False
    )
    set_clock("2026-06-01T00:00:00Z")
    app = open_application(applicant["id"])
    node = add_node(
        app["id"], applicant["id"], ss["id"], seg["id"],
        facility_type="NEW_POLE", proposed_construction_date=construction_date,
    )
    submit(app["id"], applicant["id"])
    record_completeness(app["id"], complete=True)
    return ss, node


def test_new_pole_construction_inside_moratorium_rejected(api):
    """PRD §3.4: "For a new-pole node, the `proposed_construction_date` must not
    fall within the segment's pavement moratorium — the half-open window running
    from `last_paved_at` up to but not including `last_paved_at` plus
    `moratorium_months` months — otherwise it is rejected with `ERR_PAVEMENT_MORATORIUM`;"

    Design: Difficulty/resource_temporal_overlap/new_pole_construction_within_pavement_moratorium
    """
    ss, node = _new_pole_under_review("2026-06-15T00:00:00Z")  # inside [2026-01-01, 2029-01-01)
    ss_ver = structure_version(ss["id"])
    res = api.design_review(node["id"], design_review_payload(ss_ver, outcome="PASS"), ROW)
    validate_error(res, "ERR_PAVEMENT_MORATORIUM", 409)


def test_new_pole_construction_at_window_start_rejected(api):
    """PRD §3.4: "the half-open window running from `last_paved_at` up to but not
    including `last_paved_at` plus `moratorium_months` months — otherwise it is
    rejected with `ERR_PAVEMENT_MORATORIUM`;"

    Design: Difficulty/resource_temporal_overlap/new_pole_construction_within_pavement_moratorium
    """
    ss, node = _new_pole_under_review("2026-01-01T00:00:00Z")  # inclusive window start
    ss_ver = structure_version(ss["id"])
    res = api.design_review(node["id"], design_review_payload(ss_ver, outcome="PASS"), ROW)
    validate_error(res, "ERR_PAVEMENT_MORATORIUM", 409)


# ─── Difficulty: structure_slot_conservation_reserve_release ──────────────
def test_aesthetic_fail_releases_reserved_slot(api):
    """PRD §3.4: "A node joins to `REJECTED` as soon as either dimension is `FAIL`;
    if that node had already reserved a slot from a prior design pass, the rejection
    releases it by decrementing the structure's `reserved_collocations`."

    Design: Difficulty/compensating_invariant/structure_slot_conservation_reserve_release
    """
    ctx = setup_under_review_single(
        structure_kwargs={"max_collocations": 2},
        segment_kwargs={"in_historic_district": True},
    )
    record_design_review(ctx["node"]["id"], ctx["structure"]["id"], outcome="PASS")
    record_aesthetic_review(ctx["node"]["id"], outcome="FAIL")
    node = fetch_node(ctx["node"]["id"])
    structure = fetch_structure(ctx["structure"]["id"])
    assert node["status"] == "REJECTED"
    assert structure["reserved_collocations"] == 0


def test_slot_counts_conserve_max_after_release(api):
    """PRD §2.7: "The computed `available_collocations` is always `max_collocations`
    minus `reserved_collocations` minus `active_collocations`."

    Design: Difficulty/compensating_invariant/structure_slot_conservation_reserve_release
    """
    ctx = setup_under_review_single(
        structure_kwargs={"max_collocations": 2},
        segment_kwargs={"in_historic_district": True},
    )
    record_design_review(ctx["node"]["id"], ctx["structure"]["id"], outcome="PASS")
    record_aesthetic_review(ctx["node"]["id"], outcome="FAIL")
    structure = fetch_structure(ctx["structure"]["id"])
    assert structure["available_collocations"] == 2
    assert (
        structure["reserved_collocations"]
        + structure["active_collocations"]
        + structure["available_collocations"]
        == structure["max_collocations"] == 2
    )


# ─── Corner: new_pole_after_moratorium_window_passes ──────────────────────
def test_new_pole_after_moratorium_window_passes(api):
    """PRD §3.4: "For a new-pole node, the `proposed_construction_date` must not
    fall within the segment's pavement moratorium — the half-open window running
    from `last_paved_at` up to but not including `last_paved_at` plus
    `moratorium_months` months — otherwise it is rejected with `ERR_PAVEMENT_MORATORIUM`;
    a segment with a null `last_paved_at` imposes no such window."

    Design: Corner/calculations/new_pole_after_moratorium_window_passes
    """
    ss, node = _new_pole_under_review("2029-06-15T00:00:00Z")  # after [2026-01-01, 2029-01-01)
    ss_ver = structure_version(ss["id"])
    res = api.design_review(node["id"], design_review_payload(ss_ver, outcome="PASS"), ROW)
    review = validate_success(res, 201)
    assert review["outcome"] == "PASS"
    updated = fetch_node(node["id"])
    assert updated["design_review_status"] == "PASS"
    assert updated["status"] == "APPROVED"  # aesthetic auto-WAIVED (non-historic, NONE district)


# ─── Corner: design_review_on_terminal_node_rejected ──────────────────────
def test_design_review_on_rejected_node_rejected(api):
    """PRD §3.4: "A design review is admissible only when the node is `IN_REVIEW`,
    its parent application is `UNDER_REVIEW`, and the referenced support structure
    is `ACTIVE`;"

    Design: Corner/state_machines/design_review_on_terminal_node_rejected
    """
    ctx = setup_under_review_single()
    record_design_review(ctx["node"]["id"], ctx["structure"]["id"], outcome="FAIL")
    node = fetch_node(ctx["node"]["id"])
    assert node["status"] == "REJECTED"
    ss_ver = structure_version(ctx["structure"]["id"])
    res = api.design_review(ctx["node"]["id"], design_review_payload(ss_ver, outcome="PASS"), ROW)
    validate_error(res, "ERR_INVALID_STATE", 409)


# ─── Corner: occ_stale_structure_version_on_design_review ─────────────────
def test_stale_structure_version_on_design_review_rejected(api):
    """PRD §2.6: "Because a design pass reserves a physical slot and advances the
    structure's version, a reviewer whose `expected_support_structure_version` is
    behind the structure's current version is working from a stale view of remaining
    capacity, and the review is rejected with `ERR_STALE_VERSION`."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_structure_version_on_design_review
    """
    ss, n1, n2 = _two_node_batch_under_review(max_collocations=3)
    ss_ver_pre = structure_version(ss["id"])
    # First PASS advances the structure version.
    validate_success(api.design_review(n1["id"], design_review_payload(ss_ver_pre, outcome="PASS"), ROW), 201)
    # Second review still carries the pre-first version → stale.
    res = api.design_review(n2["id"], design_review_payload(ss_ver_pre, outcome="PASS"), ROW)
    validate_error(res, "ERR_STALE_VERSION", 412)
