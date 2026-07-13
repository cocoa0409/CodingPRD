"""Art-proof approval cycle, version-pin cascade, ownership, and OCC on line version."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_customer_headers,
    create_customer_payload, create_art_proof_payload,
    setup_draft_line, setup_submitted_proof, setup_approved_proof,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
AM = TEST_USERS["account_manager_headers"]


# ---- queue A: cyclic revision then approval ------------------------------

def test_revision_cycle_reaches_approved(api):
    """PRD 3.3: "The buyer may reject it, moving it from `PENDING_APPROVAL` to
    `CHANGES_REQUESTED` and optionally attaching revised notes; from there the
    `AccountManager` resubmits, moving `CHANGES_REQUESTED` back to `PENDING_APPROVAL` and
    closing the revision loop. Alternatively the buyer approves it, moving
    `PENDING_APPROVAL` to `APPROVED`."

    Design: Difficulty/non_linear_state_machine/art_proof_revision_cycle
    """
    ctx = setup_submitted_proof()
    pid, ch = ctx["proof_id"], ctx["cust_headers"]
    validate_success(api.request_changes(pid, {"notes": "make logo bigger"}, ch))
    validate_success(api.submit_proof(pid, AM))
    validate_success(api.approve_proof(pid, ch))
    proof = validate_success(api.get_art_proof(pid, AM))
    assert proof["status"] == "APPROVED"


def test_revision_cycle_pins_current_line_version_and_bubbles_line(api):
    """PRD 3.3: "On approval three things happen: the proof's `approved_version` is
    pinned to the parent line's current version; the parent line bubbles from
    `PENDING_ART` to `ART_READY`; and the order's `art_complete` is recomputed."
    PRD 3.3: "the required `expected_order_line_version` (2.7). The new proof is
    assigned a `revision_number` — 1 for the first proof on a line, incremented for
    each superseding proof — starts in status `DRAFT`, and its creation increments
    the owning line's version by one."

    Design: Difficulty/non_linear_state_machine/art_proof_revision_cycle
    """
    ctx = setup_submitted_proof()
    pid, ch = ctx["proof_id"], ctx["cust_headers"]
    validate_success(api.request_changes(pid, {"notes": "revise"}, ch))
    validate_success(api.submit_proof(pid, AM))
    validate_success(api.approve_proof(pid, ch))
    proof = validate_success(api.get_art_proof(pid, AM))
    line = validate_success(api.get_line(ctx["line_id"], AM))
    assert proof["approved_version"] == 2, (
        "line v1 at create, +1 on proof creation -> 2 pinned at approval")
    assert line["status"] == "ART_READY"


# ---- queue A: approve cascade line + order -------------------------------

def test_approve_bubbles_line_to_art_ready(api):
    """PRD 3.3: "On approval three things happen: the proof's `approved_version` is
    pinned to the parent line's current version; the parent line bubbles from
    `PENDING_ART` to `ART_READY`; and the order's `art_complete` is recomputed."

    Design: Difficulty/transitive_cascade/art_approve_line_order_artcomplete
    """
    ctx = setup_submitted_proof()
    validate_success(api.approve_proof(ctx["proof_id"], ctx["cust_headers"]))
    proof = validate_success(api.get_art_proof(ctx["proof_id"], AM))
    line = validate_success(api.get_line(ctx["line_id"], AM))
    assert proof["status"] == "APPROVED"
    assert line["status"] == "ART_READY"


def test_approve_sets_order_art_complete(api):
    """PRD 3.3: "The order's `art_complete` becomes true precisely when every
    non-cancelled line has an `APPROVED` proof."

    Design: Difficulty/transitive_cascade/art_approve_line_order_artcomplete
    """
    ctx = setup_submitted_proof()
    validate_success(api.approve_proof(ctx["proof_id"], ctx["cust_headers"]))
    order = validate_success(api.get_order(ctx["order_id"], AM))
    assert order["art_complete"] is True


# ---- corner: approve an already-approved proof ---------------------------

def test_approve_already_approved_proof_rejected(api):
    """PRD 3.3: "both require the proof to be in `PENDING_APPROVAL`, failing with
    `ERR_ART_INVALID_STATE` otherwise."

    Design: Corner/state_machines/approve_proof_twice_returns_invalid_state
    """
    ctx = setup_approved_proof()
    resp = api.approve_proof(ctx["proof_id"], ctx["cust_headers"])
    validate_error(resp, ApiErrorId.ERR_ART_INVALID_STATE)
    proof = validate_success(api.get_art_proof(ctx["proof_id"], AM))
    assert proof["status"] == "APPROVED"


# ---- corner: OCC stale line version --------------------------------------

def test_art_proof_create_stale_line_version_rejected(api):
    """PRD 2.7: "If that value does not match the line's current version — because
    another writer has created a proof and advanced the line's version since the
    client last read it — the request is rejected with `ERR_STALE_ORDER_LINE_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/art_proof_create_stale_line_version_returns_412
    """
    ctx = setup_draft_line()
    stale_v = ctx["line_version"]
    first = api.create_art_proof(
        ctx["line_id"], create_art_proof_payload(expected_order_line_version=stale_v), AM)
    validate_success(first, 201)
    second = api.create_art_proof(
        ctx["line_id"],
        create_art_proof_payload(proof_url="http://x/b.png", expected_order_line_version=stale_v),
        AM)
    validate_error(second, ApiErrorId.ERR_STALE_ORDER_LINE_VERSION)
    line = validate_success(api.get_line(ctx["line_id"], AM))
    assert line["version"] == 2, "the first successful create advanced the line to version 2"


# ---- corner: non-owner cannot approve ------------------------------------

def test_customer_cannot_approve_other_customers_proof(api):
    """PRD 2.1: "when a Customer acts on a resource that belongs to a different
    customer, the request is rejected with `ERR_NOT_ORDER_OWNER` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_approve_other_customers_proof_returns_not_owner
    """
    ctx = setup_submitted_proof()
    other = validate_success(api.create_customer(create_customer_payload(name="AcmeB"), ADMIN), 201)
    other_headers = make_customer_headers(other["id"])
    resp = api.approve_proof(ctx["proof_id"], other_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_ORDER_OWNER)
    proof = validate_success(api.get_art_proof(ctx["proof_id"], AM))
    assert proof["status"] == "PENDING_APPROVAL"
