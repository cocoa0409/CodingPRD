"""Pricing, ACH fees, dividend allocation arithmetic, and numeric boundaries.

Translates difficulty-design instances under dual_variant_calc, combinatorial_formula, and
boundary_precision_check (queue A).
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    set_clock, create_fund, create_share_class, create_approved_investor,
    create_subscription, settle_subscription, post_valuation, declare_distribution,
    create_settled_holding, fund_version, holding_version,
    setup_fund_with_settled_holding, setup_three_holdings_for_distribution,
    advance_valuations, create_redemption_request,
    make_operator_headers, make_investor_headers,
)

OP = make_operator_headers()


# ===========================================================================
# Rule 1a — subscription_provisional_vs_final_nav_pricing
# ===========================================================================

def test_subscription_settled_nav_diverges_from_provisional_after_valuation(api):
    """PRD §3.4: "It captures `settled_nav_cents` as the fund's `nav_per_share_cents` at the
    settlement instant — the **final** price, which diverges from the earlier provisional quote
    whenever a valuation posted between create and settle."
    PRD §3.4: "At create time the system captures a **provisional** price quote, recording the
    fund's current `nav_per_share_cents` into the subscription's `provisional_nav_cents`".
    PRD §3.4: "It mints `shares_allocated` as `funded_amount_cents` divided by `settled_nav_cents`,
    rounded half up to four decimal places."

    Design: Difficulty/dual_variant_calc/subscription_provisional_vs_final_nav_pricing
    """
    set_clock("2026-03-01T00:00:00Z")
    # gross_asset = 1,000,000 so that after A settles 1,000,000 at par (NAV 1000 -> 1000 shares),
    # the recomputed NAV is 1,000,000 / 1000 = 1000 (PRD §3.1 NAV = net assets / shares).
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)

    # Investor A subscribes 1,000,000 at NAV 1000 -> 1000 shares; NAV stays 1000.
    inv_a = create_approved_investor()
    sub_a = create_subscription(fund["id"], inv_a["id"], sc["id"], 1_000_000)
    settle_subscription(sub_a["id"])

    # Investor B subscribes 500,000 while NAV is still 1000 (provisional quote captured).
    inv_b = create_approved_investor()
    fund_v_pre_b = fund_version(fund["id"])
    sub_b = create_subscription(fund["id"], inv_b["id"], sc["id"], 500_000,
                                expected_fund_version=fund_v_pre_b)
    assert sub_b["provisional_nav_cents"] == 1000

    # A valuation moves NAV to 1250 (net 1,250,000 / 1000 shares) before B settles.
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=1_250_000, total_liabilities_cents=0)

    settled_b = settle_subscription(sub_b["id"])
    assert settled_b["provisional_nav_cents"] == 1000
    assert settled_b["settled_nav_cents"] == 1250
    assert settled_b["shares_allocated"] == 400.0000
    assert settled_b["provisional_nav_cents"] != settled_b["settled_nav_cents"]


def test_subscription_provisional_quote_captured_at_create(api):
    """PRD §3.4: "At create time the system captures a **provisional** price quote, recording the
    fund's current `nav_per_share_cents` into the subscription's `provisional_nav_cents`; this
    quote is purely informational — no shares are minted from it."

    Design: Difficulty/dual_variant_calc/subscription_provisional_vs_final_nav_pricing
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=100_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 500_000)
    # No shares exist yet -> NAV is the par bootstrap 1000, captured provisionally; not minted.
    assert sub["provisional_nav_cents"] == 1000
    assert sub["status"] == "PENDING_ACH"
    assert sub.get("shares_allocated") is None


# ===========================================================================
# Rule 1b — early_withdrawal_penalty_tier_vs_dividend_per_share_allocation
# ===========================================================================

def test_force_fulfill_penalty_tier2_net_proceeds(api):
    """PRD §3.7: "The `penalty_cents` is `gross_value_cents` multiplied by the rate in basis
    points divided by ten thousand, rounded half up to whole cents, and the `net_proceeds_cents`
    is `gross_value_cents` minus `penalty_cents`."
    PRD §3.7: "an age of at least 4 but fewer than 8 quarters draws 200 basis points".

    Design: Difficulty/dual_variant_calc/early_withdrawal_penalty_tier_vs_dividend_per_share_allocation
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    # Settle 5,000,000 at par (bootstrap NAV 1000, shares==0) -> 5000 shares; total_capital
    # 5,000,000 -> quarterly redemption cap = 5% = 250,000, which accommodates the 205,000 gross
    # of the redemption below (PRD §3.7 force-fulfill is subject to the 5% cap).
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 5_000_000)
    settled = settle_subscription(sub["id"])  # first_acquired_seq = 0
    holding_id = settled["holding_id"]

    # Advance to seq 5 (age 5 -> tier2 200bps), final NAV 1025 (net 5,125,000 / 5000 shares).
    for i, (label, gross) in enumerate([
        ("2026-Q1", 5_000_000), ("2026-Q2", 5_000_000), ("2026-Q3", 5_000_000),
        ("2026-Q4", 5_000_000), ("2027-Q1", 5_125_000),
    ]):
        post_valuation(fund["id"], period_label=label,
                       gross_asset_value_cents=gross, total_liabilities_cents=0)

    rr = create_redemption_request(holding_id, 200, inv["id"])
    fulfilled = get_success_data(api.force_fulfill_redemption(rr["id"], OP))
    # gross = round(200 * 1025) = 205000; penalty = round(205000 * 0.02) = 4100; net = 200900.
    assert fulfilled["penalty_tier_rate_bps"] == 200
    assert fulfilled["penalty_cents"] == 4100
    assert fulfilled["net_proceeds_cents"] == 200900


def test_distribution_per_share_payout_round_per_holding(api):
    """PRD §3.6: "For each eligible holding the **gross dividend** is that holding's `shares_owned`
    multiplied by the distribution's `dividend_per_share_cents`, rounded half up to whole cents,
    and stored on the allocation as `gross_dividend_cents`."
    PRD §3.6: "The distribution's `total_paid_cents` is the **sum of the already-rounded
    per-holding `gross_dividend_cents`**".

    A holding redeemed from 1000 down to 960 shares before pay, at 1.5c/share, yields
    round(960 * 1.5) = round(1440) = 1440 (the dividend domain of the dual-domain instance).
    The redemption is kept at 40 shares so its gross (40 * 1025 = 41,000) stays under the 5%
    quarterly redemption cap (50,000 of total_capital 1,000,000, PRD §3.7).

    Design: Difficulty/dual_variant_calc/early_withdrawal_penalty_tier_vs_dividend_per_share_allocation
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000, drip_elected=False)
    settled = settle_subscription(sub["id"])  # 1000 shares at NAV 1000
    holding_id = settled["holding_id"]
    # Advance to seq 5 at NAV 1025 (net 1,025,000 / 1000 shares).
    for label, gross in [("2026-Q1", 1_000_000), ("2026-Q2", 1_000_000), ("2026-Q3", 1_000_000),
                         ("2026-Q4", 1_000_000), ("2027-Q1", 1_025_000)]:
        post_valuation(fund["id"], period_label=label,
                       gross_asset_value_cents=gross, total_liabilities_cents=0)
    # Force-fulfill 40 shares -> holding falls to 960.
    rr = create_redemption_request(holding_id, 40, inv["id"])
    get_success_data(api.force_fulfill_redemption(rr["id"], OP))
    dist = declare_distribution(fund["id"], period_label="2027-Q1", dividend_per_share_cents=1.5)
    paid = get_success_data(api.pay_distribution(dist["id"], OP))
    assert paid["total_paid_cents"] == 1440


# ===========================================================================
# Rule 2a — dividend_round_per_holding_then_sum_mode_b
# ===========================================================================

def test_dividend_round_per_holding_then_sum_three_holdings(api):
    """PRD §3.6: "The distribution's `total_paid_cents` is the **sum of the already-rounded
    per-holding `gross_dividend_cents`** — each holding's gross is rounded to whole cents first
    and only then are those rounded amounts summed, never the other way around".

    Three 33.0000-share holdings at 1.5c/share: round(33*1.5)=round(49.5)=50 each -> 150 total
    (sum-then-round would give round(148.5)=149 — the PRD pins round-per-holding-then-sum).

    Design: Difficulty/combinatorial_formula/dividend_round_per_holding_then_sum_mode_b
    """
    fund, sc, holdings, dist = setup_three_holdings_for_distribution(
        per_subscription_cents=33_000, drip_elected=False,
        gross_asset_value_cents=99_000, dividend_per_share_cents=1.5)
    paid = get_success_data(api.pay_distribution(dist["id"], OP))
    assert paid["total_paid_cents"] == 150


def test_dividend_total_paid_zero_when_no_eligible_holdings(api):
    """PRD §3.6: "the system creates one `DistributionAllocation` for each `Holding` in the
    fund's share classes whose `shares_owned` is positive".
    PRD §3.6: "The distribution's `total_paid_cents` is the **sum of the already-rounded
    per-holding `gross_dividend_cents`**".

    With no positive-balance holdings, the rounded-per-holding sum is empty -> total_paid 0.

    Design: Difficulty/combinatorial_formula/dividend_round_per_holding_then_sum_mode_b
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=99_000, total_liabilities_cents=0)
    create_share_class(fund["id"], min_investment_cents=1000)
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=99_000, total_liabilities_cents=0)
    dist = declare_distribution(fund["id"], period_label="2026-Q1", dividend_per_share_cents=1.5)
    paid = get_success_data(api.pay_distribution(dist["id"], OP))
    assert paid["total_paid_cents"] == 0


# ===========================================================================
# Rule 2b — ach_fee_waiver_circular_dependency_mode_c
# ===========================================================================

def test_ach_fee_waived_when_prelim_total_at_threshold(api):
    """PRD §3.4: "First, the raw fee is the larger of one hundred cents and the product of
    `funded_amount_cents` and the ACH rate of eight-tenths of one percent (0.008), that product
    rounded half up to whole cents. Second, a preliminary total is formed as `funded_amount_cents`
    plus that raw fee. Third, the waiver test: if the preliminary total is at least two and a half
    million cents, the fee is waived to zero; otherwise the fee remains the raw fee."
    PRD §3.4: "`total_charged_cents` is `funded_amount_cents` plus `ach_fee_cents`."

    funded 2,481,000: raw = round(2481000*0.008)=19848; prelim = 2,500,848 >= 2,500,000 -> waived.

    Design: Difficulty/combinatorial_formula/ach_fee_waiver_circular_dependency_mode_c
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor(annual_income_cents=500_000_000, net_worth_cents=500_000_000)
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 2_481_000)
    settled = settle_subscription(sub["id"])
    assert settled["ach_fee_cents"] == 0
    assert settled["total_charged_cents"] == 2_481_000


def test_ach_fee_applied_when_prelim_total_below_threshold(api):
    """PRD §3.4: "the raw fee is the larger of one hundred cents and the product of
    `funded_amount_cents` and the ACH rate of eight-tenths of one percent (0.008), that product
    rounded half up to whole cents."
    PRD §3.4: "otherwise the fee remains the raw fee. The settled value of `ach_fee_cents` is the
    post-waiver fee, and `total_charged_cents` is `funded_amount_cents` plus `ach_fee_cents`."

    funded 1,000,000: raw = round(1000000*0.008)=8000; prelim = 1,008,000 < 2,500,000 -> not waived.

    Design: Difficulty/combinatorial_formula/ach_fee_waiver_circular_dependency_mode_c
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settled = settle_subscription(sub["id"])
    assert settled["ach_fee_cents"] == 8000
    assert settled["total_charged_cents"] == 1_008_000


# ===========================================================================
# Rule 6a — annual_cap_inclusive_boundary_on_settle
# ===========================================================================

def test_annual_cap_settle_succeeds_exactly_at_cap(api):
    """PRD §3.4: "the cap is ten percent of the larger of the investor's `annual_income_cents`
    and `net_worth_cents`, rounded half up to whole cents, and the settle is permitted only when
    the investor's `ytd_invested_cents` plus this subscription's `funded_amount_cents` is less
    than or equal to that cap."

    cap = 10% of max(8,000,000, 12,000,000) = 1,200,000. ytd 1,000,000 + 200,000 == cap -> settles.

    Design: Difficulty/boundary_precision_check/annual_cap_inclusive_boundary_on_settle
    """
    set_clock("2026-03-01T00:00:00Z")
    # gross_asset = 1,000,000 so after sub1 settles 1,000,000 at par (NAV 1000 -> 1000 shares),
    # the recomputed NAV is 1,000,000 / 1000 = 1000 (PRD §3.1). A gross of 0 would drive NAV to 0
    # and make sub2's settle price (funded / NAV) undefined.
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor(accredited_status="NON_ACCREDITED",
                                   annual_income_cents=8_000_000, net_worth_cents=12_000_000)
    sub1 = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub1["id"])
    sub2 = create_subscription(fund["id"], inv["id"], sc["id"], 200_000)
    settled2 = settle_subscription(sub2["id"])
    assert settled2["status"] == "SETTLED"
    investor_after = get_success_data(api.get_investor(inv["id"], OP))
    assert investor_after["ytd_invested_cents"] == 1_200_000


def test_annual_cap_settle_rejected_one_cent_over(api):
    """PRD §3.4: "If that sum would exceed the cap, the settle is rejected with
    `ERR_ANNUAL_CAP_EXCEEDED` (HTTP 409). Accredited investors are not subject to this cap."

    cap 1,200,000; ytd 1,000,000 + 200,100 = 1,200,100 > cap -> ERR_ANNUAL_CAP_EXCEEDED.

    Design: Difficulty/boundary_precision_check/annual_cap_inclusive_boundary_on_settle
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor(accredited_status="NON_ACCREDITED",
                                   annual_income_cents=8_000_000, net_worth_cents=12_000_000)
    sub1 = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub1["id"])
    sub2 = create_subscription(fund["id"], inv["id"], sc["id"], 200_100)
    res = api.settle_subscription(sub2["id"], OP)
    validate_error(res, "ERR_ANNUAL_CAP_EXCEEDED")


# ===========================================================================
# Rule 6b — penalty_tier_boundary_age4_uses_tier2
# ===========================================================================

def test_penalty_tier_boundary_age_exactly_4_uses_tier2(api):
    """PRD §3.7: "an age of at least 4 but fewer than 8 quarters draws 200 basis points ...
    Thus, for example, an age of exactly 4 quarters falls into the 200-basis-point tier."
    PRD §3.7: "the position's age in quarters is the fund's `current_valuation_seq` minus the
    holding's `first_acquired_seq`".

    Holding first acquired at seq 0, redeemed at fund seq 4 -> age 4 -> tier2 (200bps).
    gross = round(100 * 1000) = 100000; penalty = round(100000*0.02) = 2000.
    total_capital 2,000,000 -> 5% cap = 100,000 accommodates the 100,000 redemption gross (PRD §3.7).

    Design: Difficulty/boundary_precision_check/penalty_tier_boundary_age4_uses_tier2
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    # Settle 2,000,000 at par (bootstrap, shares==0) -> 2000 shares; valuations keep NAV at 1000
    # (gross 2,000,000 / 2000 shares). total_capital 2,000,000 -> cap 100,000.
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 2_000_000)
    settled = settle_subscription(sub["id"])  # first_acquired_seq = 0
    holding_id = settled["holding_id"]
    advance_valuations(fund["id"], 4, gross=2_000_000)  # current_valuation_seq -> 4; NAV stays 1000
    rr = create_redemption_request(holding_id, 100, inv["id"])
    fulfilled = get_success_data(api.force_fulfill_redemption(rr["id"], OP))
    assert fulfilled["penalty_tier_rate_bps"] == 200
    assert fulfilled["penalty_cents"] == 2000


def test_penalty_tier_under_4_quarters_uses_tier1(api):
    """PRD §3.7: "an age of fewer than 4 quarters draws 300 basis points".
    PRD §3.7: "The **gross value**, `gross_value_cents`, is `shares_requested` multiplied by the
    fund's `nav_per_share_cents`, rounded half up to whole cents."

    Holding first acquired at seq 0, redeemed at fund seq 1 -> age 1 -> tier1 (300bps).
    gross = round(100 * 1000) = 100000; penalty = round(100000*0.03) = 3000.
    total_capital 2,000,000 -> 5% cap = 100,000 accommodates the 100,000 redemption gross (PRD §3.7).

    Design: Difficulty/boundary_precision_check/penalty_tier_boundary_age4_uses_tier2
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    # Settle 2,000,000 at par (bootstrap, shares==0) -> 2000 shares; valuations keep NAV at 1000
    # (gross 2,000,000 / 2000 shares). total_capital 2,000,000 -> cap 100,000.
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 2_000_000)
    settled = settle_subscription(sub["id"])
    holding_id = settled["holding_id"]
    advance_valuations(fund["id"], 1, gross=2_000_000)  # current_valuation_seq -> 1; NAV stays 1000
    rr = create_redemption_request(holding_id, 100, inv["id"])
    fulfilled = get_success_data(api.force_fulfill_redemption(rr["id"], OP))
    assert fulfilled["penalty_tier_rate_bps"] == 300
    assert fulfilled["penalty_cents"] == 3000
