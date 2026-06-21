"""Composite setup helpers for PLM workflows.

Every helper builds its preconditions from scratch via PRD-declared endpoints
(the harness wipes the database before each test). Setup calls use the lenient
get_success_data() validator so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing downstream assertion.

Operator-id discipline (PRD 2.1): X-User-ID is opaque but IS recorded and later
compared for segregation-of-duties and task-assignment. ECOs are created by a
ChangeAdmin operator id "ca1" and approved by Approver operator ids ("ap1",
"ap2", ...) distinct from "ca1", so the segregation check always passes during
ordinary setup.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_change_admin_headers,
    make_approver_headers,
)
from . import factories


# Canonical operator ids for the change pipeline.
CA = "ca1"          # ChangeAdmin operator
AP1 = "ap1"         # Approver operator 1
AP2 = "ap2"         # Approver operator 2

DESIGNER = TEST_USERS["designer_headers"]
SUPPLIER_MGR = TEST_USERS["supplier_manager_headers"]
QUALITY = TEST_USERS["quality_engineer_headers"]
VIEWER = TEST_USERS["viewer_headers"]
CHANGE_ADMIN = make_change_admin_headers(CA)


# ---------------------------------------------------------------------------
# Tier 1 / 2: primitive builders
# ---------------------------------------------------------------------------
def create_supplier(**overrides) -> dict:
    resp = api_client.create_supplier(
        factories.create_supplier_payload(**overrides), SUPPLIER_MGR
    )
    return get_success_data(resp)


def create_part(part_type="MAKE", **overrides) -> dict:
    resp = api_client.create_part(
        factories.create_part_payload(part_type=part_type, **overrides), DESIGNER
    )
    return get_success_data(resp)


def create_buy_part(base_cost_cents=100, supplier_id=None, **overrides) -> dict:
    """A BUY leaf part (requires a default supplier)."""
    if supplier_id is None:
        supplier_id = create_supplier()["id"]
    return create_part(
        part_type="BUY",
        base_cost_cents=base_cost_cents,
        default_supplier_id=supplier_id,
        **overrides,
    )


def create_revision(part_id) -> dict:
    """Create a WORKING revision off a part, reading the part's current version
    first so the OCC expected_part_version is correct."""
    part = get_success_data(api_client.get_part(part_id, DESIGNER))
    resp = api_client.create_revision(
        part_id,
        factories.create_revision_payload(expected_part_version=part["version"]),
        DESIGNER,
    )
    return get_success_data(resp)


def add_bom_line(revision_id, child_part_id, quantity, scrap_factor=None) -> dict:
    """Add a BOM line, reading the revision's current version for the OCC token."""
    rev = get_success_data(api_client.get_revision(revision_id, DESIGNER))
    payload = factories.create_bom_line_payload(
        child_part_id=child_part_id,
        quantity=quantity,
        expected_part_revision_version=rev["version"],
    )
    if scrap_factor is not None:
        payload["scrap_factor"] = scrap_factor
    resp = api_client.add_bom_line(revision_id, payload, DESIGNER)
    return get_success_data(resp)


def create_make_revision_with_bom(child_part_id, quantity=1, base_cost_cents=0):
    """A MAKE part with one WORKING revision consuming `child_part_id`.
    Returns (part, revision)."""
    part = create_part(part_type="MAKE", base_cost_cents=base_cost_cents)
    rev = create_revision(part["id"])
    add_bom_line(rev["id"], child_part_id, quantity)
    return part, rev


# ---------------------------------------------------------------------------
# ECR helpers
# ---------------------------------------------------------------------------
def create_approved_ecr(part_id, reason_code="DESIGN_DEFECT") -> dict:
    """Create -> submit -> approve an ECR for `part_id`. Returns APPROVED ECR."""
    ecr = get_success_data(
        api_client.create_change_request(
            factories.create_change_request_payload(part_id, reason_code=reason_code),
            DESIGNER,
        )
    )
    get_success_data(api_client.submit_change_request(ecr["id"], DESIGNER))
    return get_success_data(api_client.approve_change_request(ecr["id"], CHANGE_ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: ECO lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_draft_eco(part_id, revision_id, effectivity_date="2026-01-02T00:00:00Z",
                     required_approvals=1, assignees=None):
    """Approved ECR -> DRAFT ECO with one affected item (revision_id) and N
    approval tasks. Returns (eco, [task_ids])."""
    if assignees is None:
        assignees = [AP1] if required_approvals == 1 else [AP1, AP2][:required_approvals]
    ecr = create_approved_ecr(part_id)
    eco = get_success_data(
        api_client.create_change_order(
            factories.create_change_order_payload(
                ecr["id"], effectivity_date, required_approvals=required_approvals
            ),
            CHANGE_ADMIN,
        )
    )
    get_success_data(
        api_client.add_affected_item(
            eco["id"], factories.create_affected_item_payload(revision_id), CHANGE_ADMIN
        )
    )
    task_ids = []
    for assignee in assignees:
        task = get_success_data(
            api_client.add_approval_task(
                eco["id"], factories.create_approval_task_payload(assignee), CHANGE_ADMIN
            )
        )
        task_ids.append(task["id"])
    return eco, task_ids


def create_in_approval_eco(part_id, revision_id, effectivity_date="2026-01-02T00:00:00Z",
                           required_approvals=1, assignees=None):
    """DRAFT ECO -> submit-for-approval -> IN_APPROVAL. Returns (eco, [task_ids]).
    The affected revision should already be IN_REVIEW for a later release."""
    eco, task_ids = create_draft_eco(
        part_id, revision_id, effectivity_date, required_approvals, assignees
    )
    get_success_data(api_client.submit_eco_for_approval(eco["id"], CHANGE_ADMIN))
    return eco, task_ids


def create_approved_eco(part_id, revision_id, effectivity_date="2026-01-02T00:00:00Z"):
    """Full path to an APPROVED ECO with one approval task (ap1) that approved it.
    The affected revision is IN_REVIEW. Returns (eco, task_id, revision_id)."""
    eco, task_ids = create_in_approval_eco(
        part_id, revision_id, effectivity_date, required_approvals=1
    )
    get_success_data(api_client.approve_task(task_ids[0], make_approver_headers(AP1)))
    return eco, task_ids[0]


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, CHANGE_ADMIN))


def make_effective(eco_id):
    return get_success_data(api_client.make_change_order_effective(eco_id, CHANGE_ADMIN))


# ---------------------------------------------------------------------------
# Tier 3: release a revision end-to-end (the dominant shared preamble)
# ---------------------------------------------------------------------------
def release_revision(part_id, revision_id, effectivity_date="2026-01-02T00:00:00Z",
                     clock_after="2026-01-03T00:00:00Z"):
    """Take an IN_REVIEW revision all the way to RELEASED via the ECO flow:
    approved ECR -> ECO -> affected item -> approval task -> submit -> approve ->
    advance clock -> make-effective. The revision must already be IN_REVIEW.
    Returns the EFFECTIVE eco dict."""
    eco, _task = create_approved_eco(part_id, revision_id, effectivity_date)
    set_clock(clock_after)
    return make_effective(eco["id"])


def create_released_make_part(child_buy_cost=100, quantity=1, base_cost_cents=0):
    """A MAKE part whose first revision (A) is RELEASED, consuming one BUY leaf.
    Returns (part, revision, leaf_part)."""
    leaf = create_buy_part(base_cost_cents=child_buy_cost)
    part = create_part(part_type="MAKE", base_cost_cents=base_cost_cents)
    rev = create_revision(part["id"])
    add_bom_line(rev["id"], leaf["id"], quantity)
    get_success_data(api_client.submit_revision_review(rev["id"], DESIGNER))
    release_revision(part["id"], rev["id"])
    rev = get_success_data(api_client.get_revision(rev["id"], DESIGNER))
    return part, rev, leaf


# ---------------------------------------------------------------------------
# Tier 4: serialized-unit and deviation accumulation
# ---------------------------------------------------------------------------
def create_built_unit(revision_id) -> dict:
    """A SerializedUnit pinned to a RELEASED revision, advanced PLANNED->BUILT.
    Returns the BUILT unit."""
    unit = get_success_data(
        api_client.create_serialized_unit(
            factories.create_serialized_unit_payload(revision_id), QUALITY
        )
    )
    return get_success_data(api_client.build_serialized_unit(unit["id"], QUALITY))


def create_nonconforming_unit(revision_id) -> dict:
    """A BUILT unit on a RELEASED revision, manually flagged NONCONFORMING."""
    unit = create_built_unit(revision_id)
    return get_success_data(api_client.flag_unit_nonconforming(unit["id"], QUALITY))


def create_submitted_deviation(part_id, effective_from, effective_to,
                               defect_code="COSMETIC", max_units=1, **overrides) -> dict:
    """Create -> submit a deviation. Returns the SUBMITTED deviation."""
    dev = get_success_data(
        api_client.create_deviation(
            factories.create_deviation_payload(
                part_id, effective_from, effective_to,
                defect_code=defect_code, max_units=max_units, **overrides,
            ),
            DESIGNER,
        )
    )
    return get_success_data(api_client.submit_deviation(dev["id"], DESIGNER))


def create_granted_deviation(part_id, effective_from, effective_to,
                             defect_code="COSMETIC", max_units=1, **overrides) -> dict:
    """Create -> submit -> grant a deviation. Returns the GRANTED deviation."""
    dev = create_submitted_deviation(
        part_id, effective_from, effective_to,
        defect_code=defect_code, max_units=max_units, **overrides,
    )
    return get_success_data(api_client.grant_deviation(dev["id"], QUALITY))


def create_assessed_pcn(supplier_id, affected_part_id) -> dict:
    """Create a PCN and move it RECEIVED -> UNDER_ASSESSMENT. Returns the PCN."""
    pcn = get_success_data(
        api_client.create_pcn(
            factories.create_pcn_payload(supplier_id, affected_part_id), SUPPLIER_MGR
        )
    )
    return get_success_data(api_client.assess_pcn(pcn["id"], SUPPLIER_MGR))


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------
def create_in_review_document(part_id=None, doc_type="SPEC") -> dict:
    """Create a document and move it WORKING -> IN_REVIEW. Returns the document."""
    overrides = {"doc_type": doc_type}
    if part_id is not None:
        overrides["part_id"] = part_id
    doc = get_success_data(
        api_client.create_document(factories.create_document_payload(**overrides), DESIGNER)
    )
    return get_success_data(api_client.submit_document_review(doc["id"], DESIGNER))


def create_obsolete_document(part_id=None) -> dict:
    """A document driven all the way to OBSOLETE (unattached, so release needs no
    released part). Returns the OBSOLETE document."""
    doc = create_in_review_document(part_id=part_id)
    get_success_data(api_client.release_document(doc["id"], CHANGE_ADMIN))
    return get_success_data(api_client.obsolete_document(doc["id"], CHANGE_ADMIN))
