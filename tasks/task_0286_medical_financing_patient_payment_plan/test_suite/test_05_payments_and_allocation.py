"""Payments, the allocation waterfall, payment reversal, and minimum-payment rounding.

Queue A (Difficulty) — combinatorial_formula / minimum_payment_round_then_sum_vs_sum_then_round.
Queue B (Corner)     — calculations (waterfall, empty-set minimum, payoff projection),
                       state_machines (payoff not reversible), cross_cutting
                       (reverse restores balance, forfeit-then-pay interest first).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    make_provider_headers,
    make_patient_headers,
    set_clock,
    advance_clock,
    create_enrolled_provider,
    create_active_plan,
    create_provider_promotion,
    create_active_account,
    authorize_purchase,
    create_authorized_purchase,
    open_statement,
    close_statement,
    post_payment,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ──────────────── Queue A: minimum_payment round-then-sum ────────────────
def test_minimum_payment_round_per_purchase_then_sum(api):
    """PRD §3.7: "the rounding order pinned as round-per-purchase-then-sum (never
    sum-then-round). For each `FinancedPurchase` on the account ... the line minimum is
    that open principal multiplied by the `min_payment_factor` of the purchase's governing
    `PromotionalPlan`, rounded half up to whole cents. These already-rounded line minimums
    are summed to form the raw minimum."

    Two open purchases each principal 1020 under factor 0.025: round_half_up(25.5)=26 per
    line, summed = 52 (sum-then-round of 51.0 would give 51).

    Design: Difficulty/combinatorial_formula/minimum_payment_round_then_sum_vs_sum_then_round
    """
    set_clock("2026-02-01T00:00:00Z")
    provider = create_enrolled_provider(specialty="DERMATOLOGY")
    plan = create_active_plan(plan_category="EQUAL_PAYMENT", deferred_period_months=24,
                              promo_apr=0.0, min_payment_factor=0.025)
    promotion = create_provider_promotion(provider["id"], plan["id"])
    account = create_active_account()
    authorize_purchase(provider, account, promotion, 1020)
    authorize_purchase(provider, account, promotion, 1020)
    open_statement(account["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
    set_clock("2026-02-28T00:00:00Z")
    stmt = close_statement(account["id"])
    assert stmt["minimum_payment_due_cents"] == 52


def test_minimum_payment_not_sum_then_round(api):
    """PRD §3.7: "the rounding order pinned as round-per-purchase-then-sum (never
    sum-then-round)."

    The same two-line 1020/0.025 scenario must NOT produce the sum-then-round figure 51
    (1020*0.025*2 = 51.0).

    Design: Difficulty/combinatorial_formula/minimum_payment_round_then_sum_vs_sum_then_round
    """
    set_clock("2026-02-01T00:00:00Z")
    provider = create_enrolled_provider(specialty="DERMATOLOGY")
    plan = create_active_plan(plan_category="EQUAL_PAYMENT", deferred_period_months=24,
                              promo_apr=0.0, min_payment_factor=0.025)
    promotion = create_provider_promotion(provider["id"], plan["id"])
    account = create_active_account()
    authorize_purchase(provider, account, promotion, 1020)
    authorize_purchase(provider, account, promotion, 1020)
    open_statement(account["id"], "2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")
    set_clock("2026-02-28T00:00:00Z")
    stmt = close_statement(account["id"])
    assert stmt["minimum_payment_due_cents"] != 51


# ──────────────── Queue B: calculations ────────────────
def test_payment_allocation_waterfall_soonest_promo_first(api):
    """PRD §3.4: "Open purchases ... are processed in a fixed order: soonest `promo_end`
    first, so that the purchase whose promotional window closes earliest is protected
    first, with ties broken by the purchase's `created_at` in ascending order".

    A 200,000 MANUAL payment (exactly the balance — PRD §3.4 forbids MANUAL exceeding the
    current balance) walks the waterfall across both open purchases, paying each fully and
    driving the balance to zero.

    Design: Corner/calculations/payment_allocation_waterfall_soonest_promo_first
    """
    set_clock("2026-01-01T00:00:00Z")
    provider = create_enrolled_provider()
    # Distinct plan categories so the two overlapping-window provider-promotions
    # do not collide under the same-(provider, plan_category) temporal-conflict
    # rule (PRD §3.1). The waterfall order depends only on deferred_period_months.
    plan_a = create_active_plan(plan_category="DEFERRED_INTEREST",
                                deferred_period_months=11, min_payment_factor=0.05,
                                name="11mo")
    plan_b = create_active_plan(plan_category="REDUCED_APR",
                                deferred_period_months=12, min_payment_factor=0.05,
                                name="12mo")
    pp_a = create_provider_promotion(provider["id"], plan_a["id"])
    pp_b = create_provider_promotion(provider["id"], plan_b["id"])
    account = create_active_account()
    p1 = authorize_purchase(provider, account, pp_a, 100_000)  # sooner promo_end
    p2 = authorize_purchase(provider, account, pp_b, 100_000)

    post_payment(account, 200_000, "MANUAL")
    fp1 = validate_success(api.get_financed_purchase(p1["id"], ADMIN), 200)
    fp2 = validate_success(api.get_financed_purchase(p2["id"], ADMIN), 200)
    assert fp1["principal_paid_cents"] == 100_000
    assert fp2["principal_paid_cents"] == 100_000
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert acct["current_balance_cents"] == 0


def test_minimum_payment_empty_set_is_zero(api):
    """PRD §3.7: "If the account has no open purchases the raw minimum is zero and the
    minimum due is zero."
    PRD §3.7: "`min_payment_satisfied` is true exactly when `amount_paid_in_cycle_cents`
    is greater than or equal to `minimum_payment_due_cents`."

    Design: Corner/calculations/minimum_payment_empty_set_is_zero
    """
    set_clock("2026-01-01T00:00:00Z")
    account = create_active_account()
    open_statement(account["id"], "2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z")
    set_clock("2026-01-31T00:00:00Z")
    stmt = close_statement(account["id"])
    assert stmt["minimum_payment_due_cents"] == 0
    assert stmt["min_payment_satisfied"] is True
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert acct["status"] == "ACTIVE"


def test_payoff_projection_advisory_never_posts(api):
    """PRD §3.8: "This projection is never posted to any balance. It assumes no further
    payments after the projection instant: it charges the full `promo_apr` against the
    entire remaining `principal_cents` for the whole window still remaining."
    PRD §3.8: "While a purchase is `DEFERRED`, or if it became `PAID_IN_FULL`, its
    `deferred_interest_posted_cents` stays zero."

    A fresh DEFERRED purchase principal 600,000 at promo_start projects 164189 but
    deferred_interest_posted_cents stays 0.

    Design: Corner/calculations/payoff_projection_advisory_never_posts
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=600_000, promo_apr=0.2699, requested_limit_cents=1_000_000)
    proj = validate_success(
        api.get_payoff_projection(purchase["id"], make_patient_headers(account["id"])), 200)
    assert proj["projected_forfeit_interest_cents"] == 164_189
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert fp["deferred_interest_posted_cents"] == 0
    assert fp["promo_status"] == "DEFERRED"


# ──────────────── Queue B: reversal / payoff ────────────────
def test_reverse_payoff_payment_rejected(api):
    """PRD §3.4: "A `PlatformAdmin` may reverse a posted payment, but never a `PAYOFF`:
    an attempt to reverse a payment whose `payment_type` is `PAYOFF` is rejected with
    `ERR_PAYOFF_NOT_REVERSIBLE`."

    Design: Corner/state_machines/reverse_payoff_payment_rejected
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000)
    payment = post_payment(account, 100_000, "PAYOFF")
    res = api.reverse_payment(payment["id"], ADMIN)
    validate_error(res, "ERR_PAYOFF_NOT_REVERSIBLE", expected_status=409)


def test_reverse_payment_restores_balance_no_drift(api):
    """PRD §3.4: "Reversing a `POSTED` non-payoff payment moves it to `REVERSED` and
    unwinds its allocation exactly: for each allocation line it decrements that purchase's
    `principal_paid_cents` by the line's `principal_applied_cents`, it increments the
    account's `current_balance_cents` by the payment's `amount_cents`".

    Design: Corner/cross_cutting_complexity_layers/reverse_payment_restores_balance_no_drift
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=100_000)
    payment = post_payment(account, 60_000, "MANUAL")
    reversed_payment = validate_success(api.reverse_payment(payment["id"], ADMIN), 200)
    assert reversed_payment["status"] == "REVERSED"
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert acct["current_balance_cents"] == 100_000
    assert fp["principal_paid_cents"] == 0


def test_forfeit_interest_then_payment_pays_interest_before_principal(api):
    """PRD §3.4: "Within a single purchase, money pays down any open posted deferred
    interest before it pays down principal: the interest applied is the smaller of the
    remaining payment and the open interest, then the principal applied is the smaller of
    what remains and the open principal."
    PRD §3.8: "On forfeiture the purchase's promotional axis moves
    `DEFERRED → INTEREST_FORFEITED`, the computed retroactive interest is written to
    `deferred_interest_posted_cents`, and that same amount is added to the account's
    `current_balance_cents`."

    Purchase 600,000 forfeits 164189; a 164189 MANUAL payment applies wholly to interest
    (principal_paid stays 0), leaving balance 600,000.

    Design: Corner/cross_cutting_complexity_layers/forfeit_interest_then_payment_pays_interest_before_principal
    """
    provider, plan, promotion, account, purchase = create_authorized_purchase(
        principal_cents=600_000, promo_apr=0.2699, requested_limit_cents=1_000_000)
    advance_clock("2027-01-01T00:00:00Z")
    fp = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    assert fp["deferred_interest_posted_cents"] == 164_189
    post_payment(account, 164_189, "MANUAL")
    fp_after = validate_success(api.get_financed_purchase(purchase["id"], ADMIN), 200)
    acct = validate_success(api.get_account(account["id"], ADMIN), 200)
    assert fp_after["principal_paid_cents"] == 0
    assert acct["current_balance_cents"] == 600_000
