"""Servicer loss actions (default, cancel), their OCC guard, and the activation-time
credit re-check.

Covers queue A cross_entity_state_dependency (activation depends on borrower credit),
plus queue B corner instances on default/cancel preconditions, OCC stale version, and
the default/cancel cascades.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_activated_loan,
    setup_approved_application,
    create_application,
    decide_application,
    accept_disclosure,
    make_payment,
    get_loan,
    get_borrower,
    get_settlement_for_loan,
    list_installments,
    make_servicer_headers,
    make_borrower_headers,
    loan_version_payload,
    create_loan_payload,
)

SERVICER = make_servicer_headers()


def _advance(api, iso):
    return validate_success(api.set_clock({"to_iso8601": iso}, SERVICER), 200)


def test_activation_blocked_when_borrower_credit_exhausted(api):
    """PRD §3.4: "the borrower's available_credit_cents must still be at least the
    application's financed_principal_cents at the moment of activation (otherwise
    ERR_INSUFFICIENT_CREDIT)."

    Design: Difficulty/cross_entity_state_dependency/loan_activation_depends_on_borrower_available_credit
    """
    # Borrower BC limit 50000; two approved+disclosed apps each financed 50000.
    ctx1 = setup_approved_application(cart_amount_cents=50_000, plan_type="PAY_IN_4",
                                      borrower_profile={"soft_credit_score": 620,
                                                        "annual_income_cents": 2_000_000},
                                      borrower_email="bc@x.com", accept=True)
    borrower = ctx1["borrower"]
    merchant_id = ctx1["merchant"]["id"]

    # Second application on the SAME borrower & merchant, also approved + disclosed.
    app2 = create_application(borrower["id"], merchant_id,
                              cart_amount_cents=50_000, plan_type="PAY_IN_4",
                              requested_down_payment_cents=0)
    decide_application(app2["id"], "APPROVE")
    accept_disclosure(app2["id"], borrower["id"], True)

    # Activate app1 -> consumes the entire 50000 limit.
    loan1 = validate_success(
        api.create_loan(create_loan_payload(ctx1["application"]["id"]),
                        make_borrower_headers(borrower["id"])),
        201,
    )
    assert get_borrower(borrower["id"])["available_credit_cents"] == 0

    # Activate app2 -> ERR_INSUFFICIENT_CREDIT (available 0 < financed 50000).
    resp = api.create_loan(create_loan_payload(app2["id"]),
                           make_borrower_headers(borrower["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIT.value)


def test_activation_succeeds_while_borrower_credit_sufficient(api):
    """PRD §3.4: "the borrower's available_credit_cents must still be at least the
    application's financed_principal_cents at the moment of activation (otherwise
    ERR_INSUFFICIENT_CREDIT)."

    Design: Difficulty/cross_entity_state_dependency/loan_activation_depends_on_borrower_available_credit
    """
    # Borrower BC limit 50000; a single 50000 application exactly fits the limit.
    ctx = setup_approved_application(cart_amount_cents=50_000, plan_type="PAY_IN_4",
                                     borrower_profile={"soft_credit_score": 620,
                                                       "annual_income_cents": 2_000_000},
                                     borrower_email="bc@x.com", accept=True)
    loan = validate_success(
        api.create_loan(create_loan_payload(ctx["application"]["id"]),
                        make_borrower_headers(ctx["borrower"]["id"])),
        201,
    )
    assert loan["status"] == "ACTIVE"
    # available exactly met financed (50000 >= 50000) -> activation allowed.
    assert get_borrower(ctx["borrower"]["id"])["available_credit_cents"] == 0


def test_default_on_not_delinquent_loan_returns_not_delinquent(api):
    """PRD §3.10: "The action is legal only when the loan's delinquency_status is
    DELINQUENT (otherwise ERR_NOT_DELINQUENT)".

    Design: Corner/state_machines/default_loan_not_delinquent_returns_not_delinquent
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan = get_loan(ctx["loan"]["id"])  # ACTIVE + CURRENT
    resp = api.default_loan(loan["id"], loan_version_payload(loan["version"]), SERVICER)
    validate_error(resp, ApiErrorId.ERR_NOT_DELINQUENT.value)


def test_default_delinquent_loan_writes_off_and_claws_pending_settlement(api):
    """PRD §3.10: "On default the loan's version is incremented by one, every SCHEDULED
    or LATE installment is written off to WRITTEN_OFF and excluded from
    remaining-principal accounting, any ENABLED autopay mandate is disabled, and the
    merchant settlement is handled by state: a still-PENDING settlement is clawed back
    in full to CLAWED_BACK".

    Design: Corner/state_machines/default_delinquent_loan_writes_off_installments_and_claws_pending_settlement
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               settlement_hold_days=30, clock_iso="2026-01-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]
    _advance(api, "2026-02-01T00:00:00Z")  # -> DELINQUENT
    loan = get_loan(loan_id)
    assert loan["delinquency_status"] == "DELINQUENT"

    defaulted = validate_success(
        api.default_loan(loan_id, loan_version_payload(loan["version"]), SERVICER), 200
    )
    assert defaulted["status"] == "DEFAULTED"
    assert defaulted["version"] == loan["version"] + 1

    installments = list_installments(loan_id)
    assert all(i["status"] == "WRITTEN_OFF" for i in installments)

    settlement = get_settlement_for_loan(loan_id)
    assert settlement["status"] == "CLAWED_BACK"


def test_cancel_loan_with_payments_returns_loan_has_payments(api):
    """PRD §3.10: "Cancel is legal only when no payment has yet been made on the loan —
    its total_paid_cents must be 0, otherwise ERR_LOAN_HAS_PAYMENTS".

    Design: Corner/state_machines/cancel_loan_with_payments_returns_loan_has_payments
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    make_payment(ctx["loan"]["id"], ctx["borrower"]["id"], 25_000)
    loan = get_loan(ctx["loan"]["id"])

    resp = api.cancel_loan(loan["id"], loan_version_payload(loan["version"]), SERVICER)
    validate_error(resp, ApiErrorId.ERR_LOAN_HAS_PAYMENTS.value)


def test_cancel_loan_correct_version_claws_back_settlement(api):
    """PRD §3.10: "On cancel the loan's version is incremented by one, every installment
    is moved to CANCELLED (a still-SCHEDULED installment has its amount_due_cents reduced
    to its amount_paid_cents and is excluded from posture; a LATE installment is likewise
    cancelled), the merchant settlement is clawed back in full to CLAWED_BACK, any
    autopay mandate is disabled, and the borrower and merchant aggregates are recomputed."

    Design: Corner/errors/cancel_loan_correct_version_claws_back_settlement
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               settlement_hold_days=30, clock_iso="2026-01-01T00:00:00Z")
    loan = get_loan(ctx["loan"]["id"])

    cancelled = validate_success(
        api.cancel_loan(loan["id"], loan_version_payload(loan["version"]), SERVICER), 200
    )
    assert cancelled["status"] == "CANCELLED"

    settlement = get_settlement_for_loan(loan["id"])
    assert settlement["status"] == "CLAWED_BACK"

    borrower = get_borrower(ctx["borrower"]["id"])
    assert borrower["available_credit_cents"] == 500_000, "credit restored after cancel"


def test_stale_version_on_default_rejected(api):
    """PRD §2.7: "The server compares expected_loan_version against the loan's current
    version; if a prior writer has advanced the loan's version since the client read it —
    for example, a payment-driven posture change, a competing cancel, or a competing
    default — the two values no longer match and the request is rejected with
    ERR_STALE_VERSION (HTTP 412), so the servicer never acts on out-of-date loan state."

    Design: Corner/errors/error_stale_version_on_default_with_wrong_version
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan_id = ctx["loan"]["id"]
    _advance(api, "2026-02-01T00:00:00Z")  # -> DELINQUENT so the state gate passes
    loan = get_loan(loan_id)

    resp = api.default_loan(loan_id, loan_version_payload(loan["version"] - 1), SERVICER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_version_on_cancel_rejected(api):
    """PRD §2.7: "Each of these requests must carry an expected_loan_version field whose
    value is the version of the target loan the client last observed."
    PRD §3.10: "Cancel is legal only when no payment has yet been made on the loan — its
    total_paid_cents must be 0, otherwise ERR_LOAN_HAS_PAYMENTS — and when
    expected_loan_version matches the loan's current version, otherwise ERR_STALE_VERSION
    at HTTP 412."

    Design: Corner/errors/error_stale_version_on_cancel
    """
    ctx = setup_activated_loan(cart_amount_cents=100_000, plan_type="PAY_IN_4",
                               clock_iso="2026-01-01T00:00:00Z")
    loan = get_loan(ctx["loan"]["id"])  # ACTIVE, no payments

    resp = api.cancel_loan(loan["id"], loan_version_payload(loan["version"] - 1), SERVICER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
