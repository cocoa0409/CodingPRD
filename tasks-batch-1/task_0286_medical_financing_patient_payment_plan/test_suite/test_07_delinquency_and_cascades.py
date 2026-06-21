"""Delinquency cycle, default boundary, and the refund/clawback compensation cascade.

Queue A (Difficulty) — non_linear_state_machine / patient_account_cyclic_active_delinquent_cure,
                       boundary_precision_check / third_strike_defaults_at_exactly_three,
                       transitive_cascade / refund_depth3_purchase_settlement_provider_account_delinquency,
                       compensating_invariant / refund_conserves_account_available_credit,
                       compensating_invariant / settlement_clawback_conserves_provider_net_cash.
Queue B (Corner)     — state_machines / autopay_resume_into_defaulted_account_blocked.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_provider_headers,
    make_patient_headers,
    set_clock,
    create_enrolled_provider,
    create_active_plan,
    create_provider_promotion,
    create_active_account,
    authorize_purchase,
    create_authorized_purchase,
    create_settled_paid_purchase,
    create_settled_purchase,
    open_statement,
    close_statement,
    drive_unsatisfied_cycle,
    post_payment,
    apply_refund,
    setup_defaulted_account,
)

ADMIN = TEST_USERS["admin_headers"]


# ──────────── Queue A: cyclic ACTIVE <-> DELINQUENT cure ────────────
def test_account_goes_delinquent_on_missed_minimum(api):
    """PRD §3.7: "An `ACTIVE` account that closes a statement with `min_payment_satisfied`
    false has its `delinquency_strikes` incremented by one and, when the resulting strike
    count is one or two, moves to `DELINQUENT`."

    Design: Difficulty/non_linear_state_machine/patient_account_cyclic_active_delinquent_cure
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=200_000, deferred_period_months=24, promo_apr=0.2,
        min_payment_factor=0.05)
    drive_unsatisfied_cycle(
        account["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z", "2026-01-31T00:00:00Z")
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert acct["status"] == "DELINQUENT"
    assert acct["delinquency_strikes"] == 1


def test_payment_cures_delinquent_account_back_to_active(api):
    """PRD §3.7: "A `DELINQUENT` account is cured — `delinquency_strikes` reset to zero and
    status returned to `ACTIVE` — when it closes a satisfied statement, or when a payment
    lifts the open cycle's paid-in amount to satisfy the open statement's minimum."

    Design: Difficulty/non_linear_state_machine/patient_account_cyclic_active_delinquent_cure
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=200_000, deferred_period_months=24, promo_apr=0.2,
        min_payment_factor=0.05)
    drive_unsatisfied_cycle(
        account["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z", "2026-01-31T00:00:00Z")
    delinquent = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert delinquent["status"] == "DELINQUENT"

    # Pay within the open (next) billing cycle so the payment lifts the open
    # cycle's paid-in amount to satisfy the open statement's minimum (PRD §3.7).
    set_clock("2026-02-05T00:00:00Z")
    post_payment(account, 100_000, "MANUAL")
    cured = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert cured["status"] == "ACTIVE"
    assert cured["delinquency_strikes"] == 0


# ──────────── Queue A: third strike defaults at exactly three ────────────
def test_two_strikes_stay_delinquent(api):
    """PRD §3.7: "A `DELINQUENT` account that closes another unsatisfied statement raising
    its strikes to one or two increments `delinquency_strikes` again and stays
    `DELINQUENT`."

    Design: Difficulty/boundary_precision_check/third_strike_defaults_at_exactly_three
    """
    set_clock("2026-01-01T00:00:00Z")
    provider, plan, promotion = (
        create_enrolled_provider(specialty="GENERAL"),
        create_active_plan(deferred_period_months=36, min_payment_factor=0.05),
        None,
    )
    promotion = create_provider_promotion(
        provider["id"], plan["id"], effective_end="2030-01-01T00:00:00Z")
    account = create_active_account()
    authorize_purchase(provider, account, promotion, 200_000)
    open_statement(account["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z")
    set_clock("2026-01-31T00:00:00Z")
    close_statement(account["id"])
    set_clock("2026-02-28T00:00:00Z")
    close_statement(account["id"])
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert acct["delinquency_strikes"] == 2
    assert acct["status"] == "DELINQUENT"


def test_third_strike_defaults_and_revokes_autopay(api):
    """PRD §3.7: "A `DELINQUENT` account that closes an unsatisfied statement raising
    `delinquency_strikes` to three moves to `DEFAULTED`; on default, every
    `AutopayEnrollment` on the account that is `ACTIVE` is set to `REVOKED`."

    Design: Difficulty/boundary_precision_check/third_strike_defaults_at_exactly_three
    """
    provider, plan, promotion, account, purchase, autopay = setup_defaulted_account(
        principal_cents=200_000, with_autopay=True)
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert acct["delinquency_strikes"] == 3
    assert acct["status"] == "DEFAULTED"
    ap = validate_success(api.get_autopay_enrollment(autopay["id"], ADMIN), 200)
    assert ap["status"] == "REVOKED"


# ──────────── Queue A: refund depth-3 cascade ────────────
def test_refund_depth3_cascade_claws_back_and_cures(api):
    """PRD §3.9: "A `REFUND` moves the purchase's settlement axis `SETTLED → REFUNDED` and
    drives a deeper cascade. The purchase's `Settlement` is clawed back: a `PAID`
    settlement moves `PAID → CLAWED_BACK` ... When a `PAID` settlement is clawed back, the
    provider's `settled_net_cents` is decremented by that settlement's `net_cents`".
    PRD §3.9: "The refund restores the account's `available_credit_cents` by the full
    `principal_cents` and decrements the account's `current_balance_cents` by the
    purchase's then-current outstanding ... If that decrement satisfies the open billing
    statement's minimum and the account is `DELINQUENT`, the account is cured to `ACTIVE`".

    Design: Difficulty/transitive_cascade/refund_depth3_purchase_settlement_provider_account_delinquency
    """
    set_clock("2026-01-01T00:00:00Z")
    provider = create_enrolled_provider(base_merchant_discount_rate=0.10, specialty="GENERAL")
    plan = create_active_plan(deferred_period_months=24, min_payment_factor=0.05)
    promotion = create_provider_promotion(provider["id"], plan["id"])
    account = create_active_account(requested_limit_cents=500_000)
    purchase = authorize_purchase(provider, account, promotion, 200_000)

    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    settlement = validate_success(api.settle_financed_purchase(
        fp["id"], {"expected_financed_purchase_version": fp["version"]}, ADMIN), 201)
    validate_success(api.pay_settlement(settlement["id"], ADMIN), 200)

    drive_unsatisfied_cycle(
        account["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z", "2026-01-31T00:00:00Z")
    delinquent = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert delinquent["status"] == "DELINQUENT"

    apply_refund(provider["id"], purchase["id"], "REFUND", 200_000)

    fp_after = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert fp_after["settlement_status"] == "REFUNDED"
    s_after = validate_success(api.get_settlement(settlement["id"], ADMIN), 200)
    assert s_after["status"] == "CLAWED_BACK"
    prov_after = validate_success(api.get_provider(provider["id"], ADMIN), 200)
    assert prov_after["settled_net_cents"] == 0
    acct_after = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert acct_after["current_balance_cents"] == 0
    assert acct_after["available_credit_cents"] == 500_000
    assert acct_after["status"] == "ACTIVE"
    assert acct_after["delinquency_strikes"] == 0


def test_refund_paid_settlement_drops_provider_net(api):
    """PRD §3.9: "When a `PAID` settlement is clawed back, the provider's
    `settled_net_cents` is decremented by that settlement's `net_cents`".
    PRD §3.5: "increments the provider's `settled_net_cents` by the settlement's
    `net_cents`".

    Design: Difficulty/transitive_cascade/refund_depth3_purchase_settlement_provider_account_delinquency
    """
    provider, plan, promotion, account, purchase, settlement = create_settled_paid_purchase(
        principal_cents=200_000, base_merchant_discount_rate=0.10)
    prov_before = validate_success(api.get_provider(provider["id"], ADMIN), 200)
    assert prov_before["settled_net_cents"] == 180_000  # 200,000 - 10% fee
    apply_refund(provider["id"], purchase["id"], "REFUND", 200_000)
    prov_after = validate_success(api.get_provider(provider["id"], ADMIN), 200)
    assert prov_after["settled_net_cents"] == 0


# ──────────── Queue A: compensating invariants ────────────
def test_refund_conserves_account_available_credit(api):
    """PRD §2.9: "credit conservation: an account's `available_credit_cents` always equals
    its `credit_limit_cents` minus the principal of its still-open purchases, so any
    operation that closes out a purchase's principal exposure restores that principal to
    available credit."
    PRD §3.9: "The refund restores the account's `available_credit_cents` by the full
    `principal_cents`".

    Design: Difficulty/compensating_invariant/refund_conserves_account_available_credit
    """
    provider, plan, promotion, account, purchase, settlement = create_settled_purchase(
        principal_cents=200_000, base_merchant_discount_rate=0.10,
        requested_limit_cents=500_000)
    before = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert before["available_credit_cents"] == 300_000
    apply_refund(provider["id"], purchase["id"], "REFUND", 200_000)
    after = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert after["available_credit_cents"] == 500_000
    # available + open principal (0) == credit_limit
    assert after["available_credit_cents"] + 0 == after["credit_limit_cents"]


def test_void_conserves_account_available_credit(api):
    """PRD §2.9: "credit conservation: an account's `available_credit_cents` always equals
    its `credit_limit_cents` minus the principal of its still-open purchases".
    PRD §3.9: "The void restores the account's `available_credit_cents` by the full
    `principal_cents` (upholding credit conservation)".

    A VOID on an AUTHORIZED purchase restores available_credit to the pre-purchase value,
    upholding the same conserved quantity as the refund variant.

    Design: Difficulty/compensating_invariant/refund_conserves_account_available_credit
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=200_000, requested_limit_cents=500_000)
    before = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert before["available_credit_cents"] == 300_000
    apply_refund(provider["id"], purchase["id"], "VOID", 200_000)
    after = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert after["available_credit_cents"] == 500_000
    assert after["available_credit_cents"] == after["credit_limit_cents"]


def test_settlement_clawback_conserves_provider_net_cash(api):
    """PRD §3.5: "its `settled_net_cents` is the running net cash position — the sum of
    paid settlements' net less the net of any that were later clawed back."
    PRD §3.9: "When a `PAID` settlement is clawed back, the provider's `settled_net_cents`
    is decremented by that settlement's `net_cents`".

    Pay one settlement (net 180000) then refund-claws it back → settled_net_cents returns
    to 0 (180000 paid - 180000 clawed back).

    Design: Difficulty/compensating_invariant/settlement_clawback_conserves_provider_net_cash
    """
    provider, plan, promotion, account, purchase, settlement = create_settled_paid_purchase(
        principal_cents=200_000, base_merchant_discount_rate=0.10)
    assert settlement["net_cents"] == 180_000
    apply_refund(provider["id"], purchase["id"], "REFUND", 200_000)
    s_after = validate_success(api.get_settlement(settlement["id"], ADMIN), 200)
    assert s_after["status"] == "CLAWED_BACK"
    prov = validate_success(api.get_provider(provider["id"], ADMIN), 200)
    assert prov["settled_net_cents"] == 0


def test_pending_settlement_clawback_leaves_net_unchanged(api):
    """PRD §3.9: "when a still-`PENDING` settlement is clawed back there is no change to
    the provider's figures because it was never paid."
    PRD §3.5: "its `settled_net_cents` is the running net cash position — the sum of paid
    settlements' net less the net of any that were later clawed back."

    Refunding a SETTLED-but-unpaid purchase claws back the PENDING settlement without
    changing settled_net_cents (it was never added).

    Design: Difficulty/compensating_invariant/settlement_clawback_conserves_provider_net_cash
    """
    provider, plan, promotion, account, purchase, settlement = create_settled_purchase(
        principal_cents=200_000, base_merchant_discount_rate=0.10)
    prov_before = validate_success(api.get_provider(provider["id"], ADMIN), 200)
    assert prov_before["settled_net_cents"] == 0  # PENDING settlement not yet paid
    apply_refund(provider["id"], purchase["id"], "REFUND", 200_000)
    s_after = validate_success(api.get_settlement(settlement["id"], ADMIN), 200)
    assert s_after["status"] == "CLAWED_BACK"
    prov_after = validate_success(api.get_provider(provider["id"], ADMIN), 200)
    assert prov_after["settled_net_cents"] == 0


# ──────────── Queue B: autopay resume into defaulted blocked ────────────
def test_autopay_resume_into_defaulted_account_blocked(api):
    """PRD §3.10: "resume a `PAUSED` enrollment back to `ACTIVE` (permitted only while the
    parent account is `ACTIVE` or `DELINQUENT`) ... defaulting an account revokes its
    `ACTIVE` enrollments".
    PRD §3.10: "A patient may pause an `ACTIVE` enrollment to `PAUSED`, resume a `PAUSED`
    enrollment back to `ACTIVE` (permitted only while the parent account is `ACTIVE` or
    `DELINQUENT`), or revoke an enrollment from either `ACTIVE` or `PAUSED` to the terminal
    `REVOKED`."

    A PAUSED enrollment whose account defaults stays PAUSED — the default cascade revokes
    only `ACTIVE` enrollments (PRD §3.7/§3.10) — so resume is rejected with
    ERR_INVALID_STATE because the parent account is DEFAULTED, neither ACTIVE nor
    DELINQUENT.

    Design: Corner/state_machines/autopay_resume_into_defaulted_account_blocked
    """
    set_clock("2026-01-01T00:00:00Z")
    provider = create_enrolled_provider(specialty="GENERAL")
    plan = create_active_plan(deferred_period_months=36, min_payment_factor=0.05)
    promotion = create_provider_promotion(
        provider["id"], plan["id"], effective_end="2030-01-01T00:00:00Z")
    account = create_active_account()
    authorize_purchase(provider, account, promotion, 200_000)
    autopay = validate_success(api.create_autopay_enrollment(
        {"patient_account_id": account["id"], "funding_token": "tok-gd",
         "draft_day_of_month": 10},
        make_patient_headers(account["id"])), 201)
    validate_success(api.pause_autopay_enrollment(
        autopay["id"], make_patient_headers(account["id"])), 200)

    open_statement(account["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z")
    set_clock("2026-01-31T00:00:00Z")
    close_statement(account["id"])
    set_clock("2026-02-28T00:00:00Z")
    close_statement(account["id"])
    set_clock("2026-03-31T00:00:00Z")
    close_statement(account["id"])

    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert acct["status"] == "DEFAULTED"
    # The PAUSED enrollment is not touched by the default cascade (only ACTIVE
    # enrollments are revoked on default, PRD §3.7/§3.10); it remains PAUSED.
    ap = validate_success(api.get_autopay_enrollment(autopay["id"], ADMIN), 200)
    assert ap["status"] == "PAUSED"
    res = api.resume_autopay_enrollment(autopay["id"], make_patient_headers(account["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
