"""Cross-entity state dependencies (verify gated on relationship notice,
write-off gated on debtor insolvency) and temporal-window guards (recourse
grace window, due/issue interval).

Difficulty queue A: cross_entity_state_dependency, resource_temporal_overlap.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_funding_ready, setup_outstanding_invoice, submit_invoice,
    create_relationship, create_approved_client, create_approved_debtor,
    verify_payload, buyback_payload, advance_clock,
    create_invoice_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]
FO = TEST_USERS["funding_headers"]
CO = TEST_USERS["collections_headers"]


def test_verify_blocked_when_relationship_not_noticed(api):
    """PRD §3.4: "As a cross-entity guard, the governing relationship's
    `notice_status` must already be `NOTICED`; if not, the request is rejected
    with `ERR_NOTICE_NOT_SENT`."

    Relationship still PENDING -> verify returns ERR_NOTICE_NOT_SENT; invoice
    stays SUBMITTED.

    Design: Difficulty/cross_entity_state_dependency/cesd_verify_blocked_by_relationship_notice
    """
    program = get_success_data(api.create_program({"name": "F-CESD"}, ADMIN))
    client = create_approved_client(program["id"])
    debtor = create_approved_debtor(
        program["id"], approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                          "verification_required": True})
    # Relationship NOT noticed (notice_status PENDING).
    create_relationship(client["id"], debtor["id"], noticed=False)
    invoice = submit_invoice(client["id"], debtor["id"], invoice_number="INV-CESD",
                             face_amount_cents=100000)
    res = api.verify_invoice(invoice["id"],
                             verify_payload(method="PHONE", confirmed_amount_cents=100000),
                             FO)
    validate_error(res, "ERR_NOTICE_NOT_SENT")
    after = validate_success(api.get_invoice(invoice["id"], FO), 200)
    assert after["status"] == "SUBMITTED", (
        f"invoice stays SUBMITTED, got {after['status']}")


def test_verify_succeeds_once_relationship_noticed(api):
    """PRD §3.4: "As a cross-entity guard, the governing relationship's
    `notice_status` must already be `NOTICED`; if not, the request is rejected
    with `ERR_NOTICE_NOT_SENT`." ... "On success the invoice moves `SUBMITTED →
    VERIFIED`".

    Once the relationship is NOTICED, the otherwise-identical verify moves the
    invoice to VERIFIED (confirming the gate is the relationship's notice state).

    Design: Difficulty/cross_entity_state_dependency/cesd_verify_blocked_by_relationship_notice
    """
    program = get_success_data(api.create_program({"name": "F-CESD2"}, ADMIN))
    client = create_approved_client(program["id"])
    debtor = create_approved_debtor(
        program["id"], approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                          "verification_required": True})
    create_relationship(client["id"], debtor["id"], noticed=True)  # NOTICED
    invoice = submit_invoice(client["id"], debtor["id"], invoice_number="INV-CESDOK",
                             face_amount_cents=100000)
    verified = validate_success(
        api.verify_invoice(invoice["id"],
                           verify_payload(method="PHONE", confirmed_amount_cents=100000), FO), 200)
    assert verified["status"] == "VERIFIED", (
        f"verify succeeds when relationship NOTICED, got {verified['status']}")


def test_writeoff_blocked_when_debtor_not_insolvent(api):
    """PRD §3.7: "A write-off may be taken from `OUTSTANDING` or from
    `SHORT_PAID`, and in both cases it is eligible only when the relationship is
    `NON_RECOURSE`, the debtor's status is `INSOLVENT`, and no `DILUTION`
    `Adjustment` exists on the invoice; if any of these does not hold the
    request is rejected with `ERR_WRITEOFF_NOT_ELIGIBLE`."

    Debtor still APPROVED (not INSOLVENT) -> write-off returns
    ERR_WRITEOFF_NOT_ELIGIBLE; invoice stays OUTSTANDING.

    Design: Difficulty/cross_entity_state_dependency/cesd_writeoff_blocked_unless_debtor_insolvent
    """
    ctx = setup_outstanding_invoice(
        clock_to="2026-07-01T00:00:00Z",
        face_amount_cents=100000, advance_rate_pct=0.85, recourse_type="NON_RECOURSE",
        invoice_overrides={"invoice_number": "INV-WO"})
    inv_id = ctx["invoice"]["id"]
    assert ctx["invoice"]["status"] == "OUTSTANDING"
    res = api.write_off_invoice(inv_id, UW)
    validate_error(res, "ERR_WRITEOFF_NOT_ELIGIBLE")
    after = validate_success(api.get_invoice(inv_id, FO), 200)
    assert after["status"] == "OUTSTANDING", (
        f"invoice stays OUTSTANDING (debtor APPROVED, not INSOLVENT), "
        f"got {after['status']}")


def test_writeoff_succeeds_once_debtor_insolvent(api):
    """PRD §3.7: "A write-off may be taken from `OUTSTANDING` or from
    `SHORT_PAID`, and in both cases it is eligible only when the relationship is
    `NON_RECOURSE`, the debtor's status is `INSOLVENT`, and no `DILUTION`
    `Adjustment` exists on the invoice ... On a permitted write-off the invoice
    moves to `WRITTEN_OFF`".

    Declaring the debtor INSOLVENT clears the eligibility gate: the NON_RECOURSE
    OUTSTANDING invoice with no dilution now writes off to WRITTEN_OFF.

    Design: Difficulty/cross_entity_state_dependency/cesd_writeoff_blocked_unless_debtor_insolvent
    """
    ctx = setup_outstanding_invoice(
        clock_to="2026-07-01T00:00:00Z",
        face_amount_cents=100000, advance_rate_pct=0.85, recourse_type="NON_RECOURSE",
        invoice_overrides={"invoice_number": "INV-WO2"})
    inv_id = ctx["invoice"]["id"]
    validate_success(api.declare_insolvent(ctx["debtor"]["id"], UW), 200)
    written = validate_success(api.write_off_invoice(inv_id, UW), 200)
    assert written["status"] == "WRITTEN_OFF", (
        f"write-off eligible once debtor INSOLVENT, got {written['status']}")


def test_outstanding_buyback_blocked_inside_grace_window(api):
    """PRD §3.7: "A buyback may also be taken from an `OUTSTANDING` invoice, but
    only when the relationship is `RECOURSE` ... and only after the recourse
    grace window has elapsed, namely when the current clock is later than the
    `due_date` plus the program's `recourse_grace_days`; if the grace window is
    still active the request is rejected with `ERR_RECOURSE_GRACE_ACTIVE`."

    Clock 2026-07-01 is not strictly past due (2026-05-31) + 90 days (2026-08-29)
    -> ERR_RECOURSE_GRACE_ACTIVE; invoice stays OUTSTANDING.

    Design: Difficulty/resource_temporal_overlap/rto_recourse_grace_window_blocks_outstanding_buyback
    """
    ctx = setup_outstanding_invoice(
        clock_to="2026-07-01T00:00:00Z",
        face_amount_cents=100000, advance_rate_pct=0.85, recourse_type="RECOURSE",
        recourse_grace_days=90, invoice_overrides={"invoice_number": "INV-GR"})
    inv_id = ctx["invoice"]["id"]
    assert ctx["invoice"]["status"] == "OUTSTANDING"
    res = api.buyback_invoice(inv_id, buyback_payload("RECOURSE_OVERDUE"), CO)
    validate_error(res, "ERR_RECOURSE_GRACE_ACTIVE")
    after = validate_success(api.get_invoice(inv_id, FO), 200)
    assert after["status"] == "OUTSTANDING", (
        f"invoice stays OUTSTANDING inside grace window, got {after['status']}")


def test_outstanding_buyback_allowed_past_grace_window(api):
    """PRD §3.7: "and only after the recourse grace window has elapsed, namely
    when the current clock is later than the `due_date` plus the program's
    `recourse_grace_days` ... On a permitted buyback the invoice moves to
    `BOUGHT_BACK`."

    Once the clock is strictly past due (2026-05-31) + 90 days (2026-08-29) — at
    2026-08-30 — the RECOURSE OUTSTANDING buyback is permitted and the invoice
    moves to BOUGHT_BACK.

    Design: Difficulty/resource_temporal_overlap/rto_recourse_grace_window_blocks_outstanding_buyback
    """
    ctx = setup_outstanding_invoice(
        clock_to="2026-07-01T00:00:00Z",
        face_amount_cents=100000, advance_rate_pct=0.85, recourse_type="RECOURSE",
        recourse_grace_days=90, invoice_overrides={"invoice_number": "INV-GR2"})
    inv_id = ctx["invoice"]["id"]
    advance_clock("2026-08-30T00:00:00Z")  # strictly past due+90
    bought = validate_success(
        api.buyback_invoice(inv_id, buyback_payload("RECOURSE_OVERDUE"), CO), 200)
    assert bought["status"] == "BOUGHT_BACK", (
        f"buyback permitted past grace window, got {bought['status']}")


def test_invoice_due_date_equal_issue_date_rejected(api):
    """PRD §2.6: "Structural validity of the body — required fields present and
    well-typed, enum values within their allowed sets, `face_amount_cents`
    greater than zero, any `amount_cents` greater than zero, `due_date` strictly
    later than `issue_date`, and advance and concentration rates within range
    (`ERR_INVALID_REQUEST`, HTTP 422)."

    due_date == issue_date (zero-length interval) -> ERR_INVALID_REQUEST.

    Design: Difficulty/resource_temporal_overlap/rto_invoice_due_after_issue_interval_rejected
    """
    program = get_success_data(api.create_program({"name": "F-IV"}, ADMIN))
    client = create_approved_client(program["id"])
    debtor = create_approved_debtor(program["id"])
    create_relationship(client["id"], debtor["id"], noticed=False)
    payload = create_invoice_payload(
        client["id"], debtor["id"], "INV-ZERO",
        face_amount_cents=100000,
        issue_date="2026-05-01T00:00:00Z",
        due_date="2026-05-01T00:00:00Z")
    res = api.create_invoice(payload, FO)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_invoice_due_date_before_issue_date_rejected(api):
    """PRD §2.6: "Structural validity of the body — required fields present and
    well-typed, enum values within their allowed sets, `face_amount_cents`
    greater than zero, any `amount_cents` greater than zero, `due_date` strictly
    later than `issue_date`, and advance and concentration rates within range
    (`ERR_INVALID_REQUEST`, HTTP 422)."

    A due_date earlier than the issue_date (a negative-length interval) also
    violates the strictly-later rule -> ERR_INVALID_REQUEST.

    Design: Difficulty/resource_temporal_overlap/rto_invoice_due_after_issue_interval_rejected
    """
    program = get_success_data(api.create_program({"name": "F-IV2"}, ADMIN))
    client = create_approved_client(program["id"])
    debtor = create_approved_debtor(program["id"])
    create_relationship(client["id"], debtor["id"], noticed=False)
    payload = create_invoice_payload(
        client["id"], debtor["id"], "INV-NEG",
        face_amount_cents=100000,
        issue_date="2026-05-15T00:00:00Z",
        due_date="2026-05-01T00:00:00Z")
    res = api.create_invoice(payload, FO)
    validate_error(res, "ERR_INVALID_REQUEST")
