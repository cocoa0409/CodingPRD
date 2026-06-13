"""Write-offs and bad debt: the approval cascade, dispute-block guard, amount
match, segregation of duties, and role gating.

Queue A (Difficulty): write-off approval cascade (invoice -> bad_debt ->
collection_stage), write-off blocked by an open dispute. Queue B (Corner):
amount mismatch, SoD violation, unauthorized clerk approve.
"""
from test_helpers import (
    validate_success,
    validate_error,
    create_customer,
    create_invoice,
    create_dispute,
    create_pending_write_off,
    setup_written_off_invoice,
    make_collections_agent_headers,
    make_ar_manager_headers,
    create_write_off_payload,
)


# --------------------------------------------------------------------------- #
# Queue A — write-off approval cascade
# --------------------------------------------------------------------------- #
def test_writeoff_approval_marks_invoice_written_off_and_bad_debt(api, ar_manager_headers):
    """PRD §3.6: "On approval the write-off's `approved` becomes true, the
    invoice moves to `WRITTEN_OFF` with `balance_cents` set to zero, and a
    cascade fires on the customer: `bad_debt_total_cents` is incremented by the
    written-off amount".

    Design: Difficulty/transitive_cascade/writeoff_approval_cascades_invoice_writtenoff_then_baddebt_then_stage
    """
    customer, invoice, _ = setup_written_off_invoice(
        invoice_face=80_000, credit_limit_cents=200_000, name="WO"
    )
    inv_after = validate_success(api.get_invoice(invoice["id"], ar_manager_headers), 200)
    cust_after = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert inv_after["status"] == "WRITTEN_OFF"
    assert cust_after["bad_debt_total_cents"] == 80_000


def test_writeoff_approval_advances_collection_stage_to_writeoff(api, ar_manager_headers):
    """PRD §3.6: "a cascade fires on the customer: `bad_debt_total_cents` is
    incremented by the written-off amount, then `exposure_cents` is recomputed,
    then `credit_status` is re-evaluated, and finally `collection_stage` is
    advanced toward `WRITEOFF`."

    Design: Difficulty/transitive_cascade/writeoff_approval_cascades_invoice_writtenoff_then_baddebt_then_stage
    """
    customer, invoice, _ = setup_written_off_invoice(
        invoice_face=80_000, credit_limit_cents=200_000, name="WOb"
    )
    cust_after = validate_success(api.get_customer(customer["id"], ar_manager_headers), 200)
    assert cust_after["collection_stage"] == "WRITEOFF"


# --------------------------------------------------------------------------- #
# Queue A — write-off blocked by open dispute
# --------------------------------------------------------------------------- #
def test_writeoff_blocked_by_open_dispute(api, ar_manager_headers):
    """PRD §3.6: "A write-off cannot be raised, nor later approved, against an
    invoice that has a dispute in `OPEN` or `UNDER_REVIEW`; such an attempt is
    rejected with `ERR_DISPUTE_BLOCKS_WRITEOFF` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/writeoff_blocked_by_open_dispute_on_invoice
    """
    customer = create_customer(name="CE1")
    invoice = create_invoice(customer["id"], face_amount_cents=60_000)
    create_dispute(invoice["id"], 10_000, "SHORTAGE")  # OPEN dispute on the invoice
    headers = make_collections_agent_headers("agent-1")
    res = api.create_write_off(
        create_write_off_payload(invoice["id"], 50_000, reason_code="UNCOLLECTIBLE"),
        headers,
    )
    validate_error(res, "ERR_DISPUTE_BLOCKS_WRITEOFF")


def test_writeoff_creation_blocked_distinct_from_credit_gate(api, ar_manager_headers):
    """PRD §3.6: "A write-off cannot be raised, nor later approved, against an
    invoice that has a dispute in `OPEN` or `UNDER_REVIEW`; such an attempt is
    rejected with `ERR_DISPUTE_BLOCKS_WRITEOFF` (HTTP 409)."

    A second invoice (no dispute) is unaffected, confirming the block keys on the
    disputed invoice's own dispute state rather than a customer-wide flag.

    Design: Difficulty/cross_entity_state_dependency/writeoff_blocked_by_open_dispute_on_invoice
    """
    customer = create_customer(name="CE1b")
    disputed_inv = create_invoice(customer["id"], face_amount_cents=60_000)
    create_dispute(disputed_inv["id"], 60_000, "SHORTAGE")  # full-balance dispute
    headers = make_collections_agent_headers("agent-2")
    res = api.create_write_off(
        create_write_off_payload(disputed_inv["id"], 60_000, reason_code="UNCOLLECTIBLE"),
        headers,
    )
    validate_error(res, "ERR_DISPUTE_BLOCKS_WRITEOFF")


# --------------------------------------------------------------------------- #
# Queue B — corner cases
# --------------------------------------------------------------------------- #
def test_writeoff_amount_mismatch_rejected(api, ar_manager_headers):
    """PRD §3.6: "The amount must equal the invoice's dunnable balance exactly —
    its `balance_cents` minus its `disputed_amount_cents` — or the request is
    rejected with `ERR_WRITEOFF_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/writeoff_amount_mismatch_rejected
    """
    customer = create_customer(name="WM")
    invoice = create_invoice(customer["id"], face_amount_cents=80_000)
    headers = make_collections_agent_headers("agent-1")
    res = api.create_write_off(
        create_write_off_payload(invoice["id"], 50_000, reason_code="UNCOLLECTIBLE"),
        headers,
    )
    validate_error(res, "ERR_WRITEOFF_AMOUNT_MISMATCH")


def test_sod_same_user_cannot_create_and_approve_writeoff(api, ar_manager_headers):
    """PRD §2.8: "On approval, the system compares the approving request's
    `X-User-ID` against the `X-User-ID` that created the write-off; if they are
    the same, the approval is rejected with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/sod_same_user_cannot_create_and_approve_writeoff
    """
    customer = create_customer(name="SD")
    invoice = create_invoice(customer["id"], face_amount_cents=40_000)
    creator = make_ar_manager_headers("manager-1")
    created = validate_success(
        api.create_write_off(
            create_write_off_payload(invoice["id"], 40_000, reason_code="UNCOLLECTIBLE"),
            creator,
        ),
        201,
    )
    approver = make_ar_manager_headers("manager-1")  # SAME operator id
    res = api.approve_write_off(created["id"], approver)
    validate_error(res, "ERR_SOD_VIOLATION")


def test_clerk_cannot_approve_writeoff(api, ar_manager_headers, ar_clerk_headers):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Write-off approval is the AR_MANAGER's exclusively; an AR_CLERK attempt is
    refused with ERR_UNAUTHORIZED.

    Design: Corner/errors/error_unauthorized_clerk_cannot_approve_writeoff
    """
    customer = create_customer(name="UZ")
    invoice = create_invoice(customer["id"], face_amount_cents=30_000)
    created = create_pending_write_off(invoice["id"], 30_000, creator_user_id="agent-1")
    res = api.approve_write_off(created["id"], ar_clerk_headers)
    validate_error(res, "ERR_UNAUTHORIZED")
