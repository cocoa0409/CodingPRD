"""Reg Z disclosure gate, request-schema validations, uniqueness, the settlement-hold
boundary, and the validation-priority pairs.

Covers queue A boundary_precision_check (settlement-hold boundary),
resource_temporal_overlap (closed-inclusive release), priority_pair_validation_conflict
(state>safety, existence>temporal), plus queue B corner instances on disclosure
immutability, invalid request, duplicates, and the Reg Z gate.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    setup_activated_loan,
    setup_approved_application,
    get_settlement_for_loan,
    create_merchant,
    create_borrower,
    create_application,
    decide_application,
    accept_disclosure,
    make_servicer_headers,
    make_borrower_headers,
    create_application_payload,
    create_disclosure_acceptance_payload,
    create_loan_payload,
    create_autopay_mandate_payload,
    create_borrower_payload,
    assert_disclosure_acceptance,
    assert_disclosure_is_immutable,
)

SERVICER = make_servicer_headers()


def _advance(api, iso):
    return validate_success(api.set_clock({"to_iso8601": iso}, SERVICER), 200)


# --------------------------------------------------------------------------
# Reg Z disclosure gate
# --------------------------------------------------------------------------
def test_activate_without_accepted_disclosure_rejected(api):
    """PRD §3.4: "activation attempted without an acceptance whose accepted is true is
    rejected with ERR_DISCLOSURE_NOT_ACCEPTED."

    Design: Corner/validations/activate_without_accepted_disclosure_returns_disclosure_not_accepted
    """
    ctx = setup_approved_application(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                     accept=False)
    resp = api.create_loan(create_loan_payload(ctx["application"]["id"]),
                           make_borrower_headers(ctx["borrower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_ACCEPTED.value)


def test_disclosure_rejected_then_activate_still_blocked(api):
    """PRD §3.4: "An acceptance with accepted set to false does not satisfy the gate;
    activation attempted without an acceptance whose accepted is true is rejected with
    ERR_DISCLOSURE_NOT_ACCEPTED."

    Design: Corner/validations/disclosure_rejected_then_activate_still_blocked
    """
    ctx = setup_approved_application(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                     accept=False)
    accept_disclosure(ctx["application"]["id"], ctx["borrower"]["id"], accepted=False)
    resp = api.create_loan(create_loan_payload(ctx["application"]["id"]),
                           make_borrower_headers(ctx["borrower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DISCLOSURE_NOT_ACCEPTED.value)


def test_disclosure_acceptance_immutable_snapshots_pay_in_4_figures(api):
    """PRD §3.4: "At creation the system snapshots the application's current figures
    onto the immutable acceptance record: disclosed_apr_bps from the application's
    apr_bps, disclosed_finance_charge_cents from its finance_charge_cents,
    disclosed_total_of_payments_cents from its total_of_payments_cents, and
    disclosed_installment_count as the number of scheduled installments."
    PRD §2.4: "It is an immutable Reg Z audit artifact and therefore carries only id and
    created_at; it has no updated_at field and no version field, because it is never
    modified after creation."

    Design: Corner/entities/disclosure_acceptance_is_immutable_no_version_field
    """
    ctx = setup_approved_application(cart_amount_cents=100_000, plan_type="PAY_IN_4")
    resp = api.create_disclosure_acceptance(
        create_disclosure_acceptance_payload(ctx["application"]["id"], accepted=True),
        make_borrower_headers(ctx["borrower"]["id"]),
    )
    data = validate_success(resp, 201)
    assert_disclosure_acceptance(data)
    assert_disclosure_is_immutable(data)
    assert data["disclosed_apr_bps"] == 0
    assert data["disclosed_finance_charge_cents"] == 0
    assert data["disclosed_installment_count"] == 4


# --------------------------------------------------------------------------
# Request-schema validations (PRD §3.2)
# --------------------------------------------------------------------------
def test_monthly_application_missing_term_months_rejected(api):
    """PRD §3.2: "For a MONTHLY plan, term_months is required and must be at least 3 and
    at most 24". PRD §3.2: "A body that violates the schema — a missing required field,
    a bad enum, term_months present for Pay-in-4 or absent for Monthly, or a requested
    down payment not strictly below the cart amount — is rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/entities/application_missing_term_months_for_monthly_returns_invalid_request
    """
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="ba@x.com")
    payload = create_application_payload(borrower["id"], merchant["id"],
                                         cart_amount_cents=120_000, plan_type="MONTHLY",
                                         requested_down_payment_cents=0)
    # term_months deliberately omitted.
    resp = api.create_application(payload, make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_pay_in_4_application_with_term_months_rejected(api):
    """PRD §3.2: "for a PAY_IN_4 plan, term_months must be omitted entirely, because
    Pay-in-4 is fixed at four bi-weekly installments."

    Design: Corner/entities/application_term_months_for_pay_in_4_returns_invalid_request
    """
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="ba@x.com")
    payload = create_application_payload(borrower["id"], merchant["id"],
                                         cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                         term_months=6, requested_down_payment_cents=0)
    resp = api.create_application(payload, make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_requested_down_payment_equal_cart_rejected(api):
    """PRD §3.2: "it defaults to 0, may be 0, must be at least 0, and must be strictly
    less than cart_amount_cents." PRD §3.2: "A body that violates the schema — a missing
    required field, a bad enum, term_months present for Pay-in-4 or absent for Monthly,
    or a requested down payment not strictly below the cart amount — is rejected with
    ERR_INVALID_REQUEST."

    Design: Corner/validations/requested_down_payment_equal_cart_returns_invalid_request
    """
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="ba@x.com")
    payload = create_application_payload(borrower["id"], merchant["id"],
                                         cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                         requested_down_payment_cents=100_000)
    resp = api.create_application(payload, make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# --------------------------------------------------------------------------
# Uniqueness / idempotency (PRD §3.1, §3.7)
# --------------------------------------------------------------------------
def test_duplicate_borrower_email_rejected(api):
    """PRD §3.1: "The email must be unique across all borrowers; reusing an email is
    rejected with ERR_DUPLICATE."

    Design: Corner/validations/duplicate_borrower_email_returns_duplicate
    """
    create_borrower(email="ba@x.com")
    resp = api.create_borrower(
        create_borrower_payload(full_name="BA2", email="ba@x.com",
                                annual_income_cents=5_000_000, soft_credit_score=700),
        SERVICER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_second_autopay_mandate_on_loan_rejected(api):
    """PRD §3.7: "At most one autopay mandate may exist per loan; a second mandate on the
    same loan is rejected with ERR_DUPLICATE."

    Design: Corner/validations/second_autopay_mandate_on_loan_returns_duplicate
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    headers = make_borrower_headers(ctx["borrower"]["id"])
    validate_success(api.create_autopay_mandate(
        create_autopay_mandate_payload(ctx["loan"]["id"]), headers), 201)

    resp = api.create_autopay_mandate(
        create_autopay_mandate_payload(ctx["loan"]["id"]), headers)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


# --------------------------------------------------------------------------
# Settlement-hold boundary (PRD §3.8)
# --------------------------------------------------------------------------
def test_settlement_release_before_hold_window_rejected_then_at_boundary_succeeds(api):
    """PRD §3.8: "the current instant must be at or after the loan's created_at plus the
    merchant's settlement_hold_days (otherwise ERR_SETTLEMENT_HOLD_ACTIVE)".

    Design: Difficulty/boundary_precision_check/settlement_hold_boundary_release_at_or_after
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               settlement_hold_days=2, clock_iso="2026-01-01T00:00:00Z")
    settlement = get_settlement_for_loan(ctx["loan"]["id"])

    _advance(api, "2026-01-02T00:00:00Z")  # before created_at + 2 days
    resp_early = api.release_merchant_settlement(settlement["id"], SERVICER)
    validate_error(resp_early, ApiErrorId.ERR_SETTLEMENT_HOLD_ACTIVE.value)

    _advance(api, "2026-01-03T00:00:00Z")  # == created_at + 2 days
    released = validate_success(
        api.release_merchant_settlement(settlement["id"], SERVICER), 200)
    assert released["status"] == "RELEASED"


def test_settlement_release_zero_hold_allowed_same_instant(api):
    """PRD §3.8: "the current instant must be at or after the loan's created_at plus the
    merchant's settlement_hold_days (otherwise ERR_SETTLEMENT_HOLD_ACTIVE)".

    Design: Difficulty/boundary_precision_check/settlement_hold_boundary_release_at_or_after
    """
    # hold_days = 0 -> created_at + 0 == created_at, so release at the activation instant
    # is at the boundary and admitted.
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               settlement_hold_days=0, clock_iso="2026-01-01T00:00:00Z")
    settlement = get_settlement_for_loan(ctx["loan"]["id"])
    released = validate_success(
        api.release_merchant_settlement(settlement["id"], SERVICER), 200)
    assert released["status"] == "RELEASED"


def test_settlement_hold_closed_inclusive_release_at_boundary(api):
    """PRD §3.8: "Release moves the settlement from PENDING to RELEASED and is legal only
    when two preconditions hold: the current instant must be at or after the loan's
    created_at plus the merchant's settlement_hold_days".

    Design: Difficulty/resource_temporal_overlap/settlement_hold_window_closed_inclusive_release
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               settlement_hold_days=2, clock_iso="2026-01-01T00:00:00Z")
    settlement = get_settlement_for_loan(ctx["loan"]["id"])

    _advance(api, "2026-01-03T00:00:00Z")  # exactly created + hold_days -> admitted
    released = validate_success(
        api.release_merchant_settlement(settlement["id"], SERVICER), 200)
    assert released["status"] == "RELEASED"


def test_settlement_release_inside_hold_window_rejected(api):
    """PRD §3.8: "the current instant must be at or after the loan's created_at plus the
    merchant's settlement_hold_days (otherwise ERR_SETTLEMENT_HOLD_ACTIVE)".

    Design: Difficulty/resource_temporal_overlap/settlement_hold_window_closed_inclusive_release
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               settlement_hold_days=2, clock_iso="2026-01-01T00:00:00Z")
    settlement = get_settlement_for_loan(ctx["loan"]["id"])
    # 2026-01-02 collides with the hold window (created + 2 days = 2026-01-03) -> rejected.
    _advance(api, "2026-01-02T00:00:00Z")
    resp = api.release_merchant_settlement(settlement["id"], SERVICER)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_HOLD_ACTIVE.value)


def test_release_already_released_settlement_returns_invalid_state(api):
    """PRD §3.8: "Release moves the settlement from PENDING to RELEASED and is legal only
    when two preconditions hold: the current instant must be at or after the loan's
    created_at plus the merchant's settlement_hold_days (otherwise
    ERR_SETTLEMENT_HOLD_ACTIVE), and the loan's lifecycle status must be ACTIVE (otherwise
    ERR_INVALID_STATE, which covers the case where the loan was cancelled or defaulted
    while the settlement was still pending)."

    Design: Corner/state_machines/settlement_release_from_already_released_returns_invalid_state
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               settlement_hold_days=0, clock_iso="2026-01-01T00:00:00Z")
    settlement = get_settlement_for_loan(ctx["loan"]["id"])
    validate_success(api.release_merchant_settlement(settlement["id"], SERVICER), 200)

    resp = api.release_merchant_settlement(settlement["id"], SERVICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------
# Validation-priority pairs (PRD §2.8)
# --------------------------------------------------------------------------
def test_activate_already_activated_application_invalid_state_beats_disclosure_gate(api):
    """PRD §2.8: "Only after those four pass does the system evaluate state-legality,
    then uniqueness/idempotency, then the domain-specific safety, temporal, and fiscal
    rules described in §3."
    PRD §3.4: "this drives the application from APPROVED to the terminal ACTIVATED
    state".

    Design: Difficulty/priority_pair_validation_conflict/activate_invalid_state_beats_disclosure_gate
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4")
    # Application is now ACTIVATED (terminal). A second activation hits the state check
    # (p5) before the Reg Z disclosure gate (p7).
    resp = api.create_loan(create_loan_payload(ctx["application"]["id"]),
                           make_borrower_headers(ctx["borrower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_activate_declined_application_invalid_state_not_disclosure_gate(api):
    """PRD §2.8: "Only after those four pass does the system evaluate state-legality,
    then uniqueness/idempotency, then the domain-specific safety, temporal, and fiscal
    rules described in §3."
    PRD §3.4: "A Borrower activates an APPROVED application by supplying the
    application_id; this drives the application from APPROVED to the terminal ACTIVATED
    state".

    Design: Difficulty/priority_pair_validation_conflict/activate_invalid_state_beats_disclosure_gate
    """
    # Application is DECLINED (not APPROVED) and has no accepted disclosure. The state
    # check (p5) fires before the Reg Z disclosure gate (p7).
    merchant = create_merchant(mdr_bps=600)
    borrower = create_borrower(email="bd@x.com", full_name="BD",
                               soft_credit_score=500, annual_income_cents=9_000_000)
    application = create_application(borrower["id"], merchant["id"],
                                    cart_amount_cents=100_000, plan_type="PAY_IN_4",
                                    requested_down_payment_cents=0)
    decide_application(application["id"], "DECLINE")
    resp = api.create_loan(create_loan_payload(application["id"]),
                           make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_release_nonexistent_settlement_not_found_beats_hold_active(api):
    """PRD §2.8: "Existence is checked third: every identifier in the path and every
    foreign-key identifier in the body must resolve to an existing resource, validated
    left-to-right, with the first unresolved identifier yielding ERR_NOT_FOUND."

    Design: Difficulty/priority_pair_validation_conflict/settlement_release_not_found_beats_hold_active
    """
    _advance(api, "2026-01-01T00:00:00Z")
    resp = api.release_merchant_settlement(NON_EXISTENT_UUID, SERVICER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_release_nonexistent_settlement_not_found_even_with_hold_active_clock(api):
    """PRD §2.8: "Existence is checked third: every identifier in the path and every
    foreign-key identifier in the body must resolve to an existing resource, validated
    left-to-right, with the first unresolved identifier yielding ERR_NOT_FOUND."
    PRD §2.8: "Only after those four pass does the system evaluate state-legality, then
    uniqueness/idempotency, then the domain-specific safety, temporal, and fiscal rules
    described in §3."

    Design: Difficulty/priority_pair_validation_conflict/settlement_release_not_found_beats_hold_active
    """
    # Even when the clock would make the hold-window check relevant for a real
    # settlement, a non-existent id fails existence (p3) first, not temporal (p8).
    _advance(api, "2026-06-01T00:00:00Z")
    resp = api.release_merchant_settlement(
        "00000000-0000-4000-8000-000000000000", SERVICER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
