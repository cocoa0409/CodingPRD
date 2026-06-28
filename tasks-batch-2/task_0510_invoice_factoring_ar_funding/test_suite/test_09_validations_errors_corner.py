"""Validation and error breadth: duplicate invoice number / relationship,
verification mismatch, party-not-approved, overpayment, debtor ceiling, credit
limit, non-recourse buyback, client-has-outstanding, program-suspended funding.

Corner queue B: validations, errors.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_funding_ready, setup_funded_invoice, setup_short_paid_invoice,
    submit_invoice, submit_and_verify_invoice, create_relationship,
    create_approved_client, create_approved_debtor, create_pending_debtor,
    create_invoice_payload, create_batch_payload, fund_batch_payload,
    verify_payload, buyback_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]
FO = TEST_USERS["funding_headers"]
CO = TEST_USERS["collections_headers"]


def _cv(api, client_id):
    return validate_success(api.get_client(client_id, FO), 200)["version"]


# ─── validations ─────────────────────────────────────────────────────────────

def test_duplicate_invoice_number_returns_409(api):
    """PRD §3.4: "The `invoice_number` must be unique per client across all of
    that client's invoices that are not in `REJECTED` status; a collision is
    rejected with `ERR_DUPLICATE_INVOICE_NUMBER`."

    Design: Corner/validations/val_duplicate_invoice_number_returns_409
    """
    parties = setup_funding_ready(noticed=False)
    client, debtor = parties["client"], parties["debtor"]
    submit_invoice(client["id"], debtor["id"], invoice_number="INV-DUP",
                   face_amount_cents=100000)
    res = api.create_invoice(
        create_invoice_payload(client["id"], debtor["id"], "INV-DUP",
                               face_amount_cents=50000), FO)
    validate_error(res, "ERR_DUPLICATE_INVOICE_NUMBER")


def test_duplicate_active_relationship_returns_409(api):
    """PRD §3.3: "Only one relationship with `status` `ACTIVE` may exist for a
    given `(client_id, debtor_id)` pair; an attempt to create a duplicate is
    rejected with `ERR_DUPLICATE_RELATIONSHIP`."

    Design: Corner/validations/val_duplicate_active_relationship_returns_409
    """
    program = get_success_data(api.create_program({"name": "P-DR"}, ADMIN))
    client = create_approved_client(program["id"])
    debtor = create_approved_debtor(program["id"])
    create_relationship(client["id"], debtor["id"], noticed=False, recourse_type="RECOURSE")
    res = api.create_relationship(
        {"client_id": client["id"], "debtor_id": debtor["id"],
         "recourse_type": "NON_RECOURSE"}, FO)
    validate_error(res, "ERR_DUPLICATE_RELATIONSHIP")


def test_verification_mismatch_returns_409(api):
    """PRD §3.4: "when the debtor's `verification_required` flag is true, the
    `confirmed_amount_cents` must equal the invoice's `face_amount_cents` and the
    `method` must not be `WAIVED`; a mismatch on either count is rejected with
    `ERR_VERIFICATION_MISMATCH`."

    Design: Corner/validations/val_verification_mismatch_returns_409
    """
    parties = setup_funding_ready(
        debtor_approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                  "verification_required": True})
    client, debtor = parties["client"], parties["debtor"]
    invoice = submit_invoice(client["id"], debtor["id"], invoice_number="INV-VM",
                             face_amount_cents=100000)
    res = api.verify_invoice(invoice["id"],
                             verify_payload(method="PHONE", confirmed_amount_cents=90000), FO)
    validate_error(res, "ERR_VERIFICATION_MISMATCH")
    after = validate_success(api.get_invoice(invoice["id"], FO), 200)
    assert after["status"] == "SUBMITTED"


def test_send_notice_party_not_approved_returns_409(api):
    """PRD §3.3: "Sending the notice requires the relationship's `notice_status`
    to be `PENDING` and, as a cross-entity guard, both the client and the debtor
    to be `APPROVED`; if either party is not approved the request is rejected
    with `ERR_PARTY_NOT_APPROVED`."

    Debtor still PENDING -> send-notice returns ERR_PARTY_NOT_APPROVED.

    Design: Corner/validations/val_party_not_approved_send_notice
    """
    program = get_success_data(api.create_program({"name": "P-PNA"}, ADMIN))
    client = create_approved_client(program["id"])
    debtor = create_pending_debtor(program["id"])
    rel = create_relationship(client["id"], debtor["id"], noticed=False)
    res = api.send_notice(rel["id"], FO)
    validate_error(res, "ERR_PARTY_NOT_APPROVED")


def test_overpayment_posting_returns_409(api):
    """PRD §3.6: "The posted amount may not exceed the invoice's remaining
    collectible face — that is, `face_amount_cents` minus `dilution_cents` minus
    the already-collected `amount_collected_cents`; an overpayment is rejected
    with `ERR_OVERPAYMENT`."

    Posting 100001 against a fresh FUNDED face-100000 invoice -> ERR_OVERPAYMENT.

    Design: Corner/validations/val_overpayment_posting_returns_409
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005,
                               invoice_overrides={"invoice_number": "INV-OV"})
    cv = _cv(api, ctx["client"]["id"])
    res = api.create_posting(
        ctx["invoice"]["id"],
        {"amount_cents": 100001, "received_at": "2026-05-10T00:00:00Z",
         "payer": "DEBTOR", "expected_client_version": cv}, CO)
    validate_error(res, "ERR_OVERPAYMENT")


# ─── errors ──────────────────────────────────────────────────────────────────

def test_debtor_ceiling_exceeded_on_fund(api):
    """PRD §3.5: "The debtor credit ceiling holds: the debtor's
    `outstanding_face_cents` plus this invoice's `face_amount_cents` must not
    exceed the debtor's `approved_credit_ceiling_cents`; otherwise
    `ERR_DEBTOR_CEILING_EXCEEDED`." PRD §3.5: "the batch moves `DRAFT → FAILED`,
    its `failure_error_id` is set to the `error_id` of the first invoice that
    failed".

    Ceiling 80000, candidate face 100000 -> ERR_DEBTOR_CEILING_EXCEEDED.

    Design: Corner/errors/err_debtor_ceiling_exceeded_on_fund
    """
    parties = setup_funding_ready(
        debtor_approve_overrides={"approved_credit_ceiling_cents": 80000,
                                  "verification_required": False})
    client, debtor = parties["client"], parties["debtor"]
    invoice = submit_and_verify_invoice(client["id"], debtor["id"],
                                        invoice_number="INV-DC", face_amount_cents=100000)
    batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [invoice["id"]], batch_reference="B-DC"), FO))
    cv = _cv(api, client["id"])
    res = api.fund_batch(batch["id"], fund_batch_payload(cv), FO)
    validate_error(res, "ERR_DEBTOR_CEILING_EXCEEDED")
    batch_after = validate_success(api.get_batch(batch["id"], FO), 200)
    assert batch_after["status"] == "FAILED"
    assert batch_after["failure_error_id"] == "ERR_DEBTOR_CEILING_EXCEEDED"


def test_credit_limit_exceeded_on_fund(api):
    """PRD §3.5: "The client credit limit holds: this invoice's computed advance
    must not exceed the client's remaining headroom, namely `credit_limit_cents`
    minus `funded_advance_outstanding_cents`; otherwise
    `ERR_CREDIT_LIMIT_EXCEEDED`."

    credit_limit 90000, face 250000 @ 0.85 -> advance 212500 > 90000 ->
    ERR_CREDIT_LIMIT_EXCEEDED.

    Design: Corner/errors/err_credit_limit_exceeded_on_fund
    """
    parties = setup_funding_ready(
        client_approve_overrides={"approved_advance_rate_pct": 0.85,
                                  "credit_limit_cents": 90000,
                                  "default_concentration_limit_pct": 0.90},
        client_overrides={"requested_advance_rate_pct": 0.85},
        debtor_approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                  "verification_required": False})
    client, debtor = parties["client"], parties["debtor"]
    invoice = submit_and_verify_invoice(client["id"], debtor["id"],
                                        invoice_number="INV-CL", face_amount_cents=250000)
    batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [invoice["id"]], batch_reference="B-CL"), FO))
    cv = _cv(api, client["id"])
    res = api.fund_batch(batch["id"], fund_batch_payload(cv), FO)
    validate_error(res, "ERR_CREDIT_LIMIT_EXCEEDED")


def test_non_recourse_no_buyback_without_dilution(api):
    """PRD §3.7: "A buyback may be taken from a `SHORT_PAID` invoice, in which
    case it is permitted when the relationship is `RECOURSE`, or when a
    `DILUTION` `Adjustment` exists on the invoice ...; if neither holds the
    request is rejected with `ERR_NON_RECOURSE_NO_BUYBACK`."

    SHORT_PAID NON_RECOURSE invoice with no DILUTION -> ERR_NON_RECOURSE_NO_BUYBACK.

    Design: Corner/errors/err_non_recourse_no_buyback
    """
    ctx = setup_short_paid_invoice(partial_amount_cents=80000,
                                   received_at="2026-06-10T00:00:00Z",
                                   clock_to="2026-06-10T00:00:00Z",
                                   face_amount_cents=100000, advance_rate_pct=0.85,
                                   fee_rate_per_day=0.0005, recourse_type="NON_RECOURSE",
                                   invoice_overrides={"invoice_number": "INV-NR"})
    inv_id = ctx["invoice"]["id"]
    assert ctx["invoice"]["status"] == "SHORT_PAID"
    res = api.buyback_invoice(inv_id, buyback_payload("CLIENT_REQUEST"), CO)
    validate_error(res, "ERR_NON_RECOURSE_NO_BUYBACK")
    after = validate_success(api.get_invoice(inv_id, FO), 200)
    assert after["status"] == "SHORT_PAID"


def test_client_has_outstanding_on_close(api):
    """PRD §3.2: "A client may be closed from either `APPROVED` or `SUSPENDED`,
    moving to `CLOSED`, but only if both its `funded_advance_outstanding_cents`
    and its `reserve_balance_cents` are exactly zero; if either is nonzero the
    close is rejected with `ERR_CLIENT_HAS_OUTSTANDING`."

    Client with one FUNDED invoice (funded_advance_outstanding 85000) -> close
    returns ERR_CLIENT_HAS_OUTSTANDING; client stays APPROVED.

    Design: Corner/errors/err_client_has_outstanding_on_close
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               invoice_overrides={"invoice_number": "INV-CHO"})
    client_id = ctx["client"]["id"]
    res = api.close_client(client_id, UW)
    validate_error(res, "ERR_CLIENT_HAS_OUTSTANDING")
    after = validate_success(api.get_client(client_id, FO), 200)
    assert after["status"] == "APPROVED"


def test_funding_blocked_when_program_suspended(api):
    """PRD §3.5: "The invoice is `VERIFIED`, the client is `APPROVED`, and the
    program is `ACTIVE`; if the client is not approved, the program is
    suspended, or (as below) the relationship is not noticed, funding is blocked
    with `ERR_FUNDING_BLOCKED`." PRD §3.1: "while suspended, no new funding may
    occur against any client in the program."

    Program suspended before fund -> ERR_FUNDING_BLOCKED, batch FAILED.

    Design: Corner/errors/err_funding_blocked_program_suspended
    """
    parties = setup_funding_ready(
        debtor_approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                  "verification_required": False})
    program, client, debtor = parties["program"], parties["client"], parties["debtor"]
    invoice = submit_and_verify_invoice(client["id"], debtor["id"],
                                        invoice_number="INV-FBS", face_amount_cents=100000)
    batch = get_success_data(api.create_batch(
        create_batch_payload(client["id"], [invoice["id"]], batch_reference="B-FBS"), FO))
    validate_success(api.suspend_program(program["id"], ADMIN), 200)
    cv = _cv(api, client["id"])
    res = api.fund_batch(batch["id"], fund_batch_payload(cv), FO)
    validate_error(res, "ERR_FUNDING_BLOCKED")
    batch_after = validate_success(api.get_batch(batch["id"], FO), 200)
    assert batch_after["status"] == "FAILED"
    assert batch_after["failure_error_id"] == "ERR_FUNDING_BLOCKED"
