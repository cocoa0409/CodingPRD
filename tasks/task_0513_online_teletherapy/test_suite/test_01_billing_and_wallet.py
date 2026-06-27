"""Billing-cycle amounts, pause proration refunds, financial-aid banding, and
wallet conservation — the money engine of the platform (PRD §3.6, §3.7).

Covers difficulty instances dual_variant_calc (pause refund), combinatorial
billing eval order, compensating wallet invariant, plus calculation corner
probes (tier discounts, banding boundaries, defaults).
"""
from test_helpers import (
    validate_success, get_success_data,
    create_client, submit_intake, get_client,
    create_subscription, subscription_with_paid_cycle, charge_cycle,
    approve_financial_aid, paused_subscription, get_subscription,
    set_clock, get_subscription_version,
    api_client,
    make_client_headers,
    factories as F,
)
from test_helpers import TEST_USERS


def _client(cid):
    return make_client_headers(cid)


def _billing():
    return TEST_USERS["billing_admin_headers"]


# ==========================================================================
# Difficulty: dual_variant_calc — pause refund (forward-looking proration)
# ==========================================================================
def test_pause_mid_week_refunds_remaining_days_to_wallet(api):
    """PRD §3.7: "The number of elapsed days is the floor of the elapsed time from
    `current_period_start` to the current clock measured in whole days; the remaining days are 7
    minus the elapsed days, floored at zero; and the refund is the paid amount multiplied by the
    remaining days divided by 7, rounded half up to whole cents."
    PRD §3.7: "Pausing moves the subscription to `PAUSED`, records `pause_resumes_on` as the
    supplied resume instant, computes a prorated refund credited to the wallet, and expires the
    current period's `AVAILABLE` credits by moving them to `EXPIRED`; the subscription's `version`
    increments."

    Design: Difficulty/dual_variant_calc/pause_refund_forward_looking_on_subscription
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"])
    charge_cycle(sub["id"])
    set_clock("2026-06-04T00:00:00Z")  # 3 full days elapsed of the 7-day period
    paused = paused_subscription(client["id"], sub["id"], "2026-07-01T00:00:00Z")
    assert paused["status"] == "PAUSED", paused
    # paid_cents 9900, elapsed_days 3, remaining 4 -> round_half_up(9900*4/7) = 5657.
    after = get_client(client["id"])
    assert after["wallet_credit_cents"] == 5657, after


def test_pause_same_day_refunds_full_paid_amount(api):
    """PRD §3.7: "a pause on the same day as the charge leaves all 7 days remaining and refunds
    the full paid amount, while a pause 7 or more days into the period leaves zero days remaining
    and refunds nothing."

    Design: Corner/calculations/pause_refund_same_day_full_refund
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"], base_weekly_fee_cents=9900)
    charge_cycle(sub["id"])
    paused = paused_subscription(client["id"], sub["id"], "2026-07-01T00:00:00Z")
    assert paused["status"] == "PAUSED", paused
    after = get_client(client["id"])
    assert after["wallet_credit_cents"] == 9900, after


# ==========================================================================
# Difficulty: combinatorial_formula — billing pins discount-before-wallet
# ==========================================================================
def test_billing_applies_discount_before_wallet(api):
    """PRD §3.6: "The cycle's amounts are computed in a pinned order — the discount is applied
    first, then the wallet last."
    PRD §3.6: "The `list_amount_cents` is the `base_weekly_fee_cents` reduced by the financial-aid
    discount and rounded half-up to whole cents, where the discount fraction is 0 for `NONE`, 0.20
    for `TIER_1`, 0.40 for `TIER_2`, and 0.60 for `TIER_3` based on the client's current
    `financial_aid_tier`."
    PRD §3.6: "The `wallet_applied_cents` is the smaller of the client's available
    `wallet_credit_cents` and the `list_amount_cents`, so wallet can zero out a cycle but the
    wallet balance never goes negative. The `charged_amount_cents` is the `list_amount_cents`
    minus the `wallet_applied_cents`."

    Design: Difficulty/combinatorial_formula/cycle_billing_pinned_eval_order_mode_c
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    # Adjusted income 3,000,000 (household 1) < 4,000,000 ceiling but >= 2,500,000 -> TIER_2 (0.40).
    approve_financial_aid(client["id"], annual_income_cents=3_000_000, household_size=1)
    sub = create_subscription(client["id"], base_weekly_fee_cents=9900, weekly_credit_grant=1)
    charge_cycle(sub["id"])  # first TIER_2 cycle: list 5940, wallet 0, charged 5940
    set_clock("2026-06-04T00:00:00Z")  # elapsed_days 3 -> refund round(5940*4/7)=3394 to wallet
    paused_subscription(client["id"], sub["id"], "2026-07-01T00:00:00Z")
    validate_success(api.resume_subscription(sub["id"], _client(client["id"])))
    set_clock("2026-06-11T00:00:00Z")
    cycle2 = validate_success(api.charge_cycle(sub["id"], _billing()), 201)
    # TIER_2 discount on base FIRST: list = round_half_up(9900*0.60) = 5940;
    # wallet LAST: min(3394, 5940) = 3394; charged = 5940 - 3394 = 2546.
    assert cycle2["list_amount_cents"] == 5940, cycle2
    assert cycle2["wallet_applied_cents"] == 3394, cycle2
    assert cycle2["charged_amount_cents"] == 2546, cycle2


def test_tier3_discount_applied_to_list_amount(api):
    """PRD §3.6: "the discount fraction is 0 for `NONE`, 0.20 for `TIER_1`, 0.40 for `TIER_2`,
    and 0.60 for `TIER_3` based on the client's current `financial_aid_tier`."

    Design: Corner/calculations/tier3_discount_full_applied
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    # Adjusted income 2,000,000 (household 1) < 2,500,000 -> TIER_3 (0.60).
    approve_financial_aid(client["id"], annual_income_cents=2_000_000, household_size=1)
    sub = create_subscription(client["id"], base_weekly_fee_cents=9900)
    cycle = validate_success(api.charge_cycle(sub["id"], _billing()), 201)
    # list = round_half_up(9900 * 0.40) = 3960; wallet 0 -> charged 3960.
    assert cycle["list_amount_cents"] == 3960, cycle
    assert cycle["charged_amount_cents"] == 3960, cycle


# ==========================================================================
# Difficulty: compensating_invariant — wallet cents conserved
# ==========================================================================
def test_wallet_cents_conserved_pause_refund_then_charge_debit(api):
    """PRD §3.7: "a pause on the same day as the charge leaves all 7 days remaining and refunds
    the full paid amount"
    PRD §3.6: "The `wallet_applied_cents` is the smaller of the client's available
    `wallet_credit_cents` and the `list_amount_cents`, so wallet can zero out a cycle but the
    wallet balance never goes negative. The `charged_amount_cents` is the `list_amount_cents`
    minus the `wallet_applied_cents`."

    Design: Difficulty/compensating_invariant/wallet_cents_conserved_on_pause_refund_then_charge_debit
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = create_subscription(client["id"], base_weekly_fee_cents=9900)
    charge_cycle(sub["id"])  # wallet starts 0
    paused_subscription(client["id"], sub["id"], "2026-07-01T00:00:00Z")  # same-day -> refund 9900
    validate_success(api.resume_subscription(sub["id"], _client(client["id"])))
    set_clock("2026-06-08T00:00:00Z")
    cycle2 = validate_success(api.charge_cycle(sub["id"], _billing()), 201)
    # list 9900, wallet min(9900,9900)=9900, charged 0; wallet debited back to net 0.
    assert cycle2["list_amount_cents"] == 9900, cycle2
    assert cycle2["wallet_applied_cents"] == 9900, cycle2
    assert cycle2["charged_amount_cents"] == 0, cycle2
    after = get_client(client["id"])
    assert after["wallet_credit_cents"] == 0, after


# ==========================================================================
# Corner: financial-aid banding boundary (above top ceiling -> NONE)
# ==========================================================================
def test_aid_at_top_ceiling_bands_to_none(api):
    """PRD §3.6: "any adjusted income of $60,000 or more awards `NONE`. Banding uses integer-cent
    subtraction only and performs no rounding."

    Design: Corner/calculations/aid_no_tier_above_top_ceiling
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    # adjusted_income = 6,000,000 (household 1) == TIER_1 ceiling, not < it -> NONE.
    app = approve_financial_aid(client["id"], annual_income_cents=6_000_000, household_size=1)
    assert app["awarded_tier"] == "NONE", app
    after = get_client(client["id"])
    assert after["financial_aid_tier"] == "NONE", after


# ==========================================================================
# Corner: subscription input defaults applied
# ==========================================================================
def test_subscription_defaults_applied(api):
    """PRD §3.6: "optionally a `base_weekly_fee_cents` (the list weekly fee before any discount,
    defaulting to 9900 and never negative) and a `weekly_credit_grant` (the number of live-session
    credits granted at the start of each cycle, defaulting to 1 and constrained between 0 and 4).
    A new `Subscription` begins in `TRIALING`."

    Design: Corner/entities/subscription_default_base_fee_applied
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(state_code="CA")
    submit_intake(client["id"], severity_score=3)
    sub = validate_success(api.create_subscription(
        F.create_subscription_payload(client["id"]), _client(client["id"])
    ), 201)
    assert sub["base_weekly_fee_cents"] == 9900, sub
    assert sub["weekly_credit_grant"] == 1, sub
    assert sub["status"] == "TRIALING", sub
