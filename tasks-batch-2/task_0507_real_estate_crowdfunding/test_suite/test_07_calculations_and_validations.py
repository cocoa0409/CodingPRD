"""Penalty / dividend calculations and business validation errors.

Translates corner-design instances under section: calculations and section: validations (queue B).
"""
import pytest

from test_helpers import (
    api_client, get_success_data, validate_error,
    set_clock, create_fund, create_share_class, create_approved_investor, create_investor,
    create_subscription, settle_subscription, post_valuation, declare_distribution,
    create_redemption_request, holding_version,
    make_operator_headers, make_fund_manager_headers, make_investor_headers,
)

OP = make_operator_headers()
FM = make_fund_manager_headers()


# ---- Section: calculations ----

def test_penalty_tier1_under_one_year_300bps(api):
    """PRD §3.7: "an age of fewer than 4 quarters draws 300 basis points".
    PRD §3.7: "The **gross value**, `gross_value_cents`, is `shares_requested` multiplied by the
    fund's `nav_per_share_cents`, rounded half up to whole cents ... The `penalty_cents` is
    `gross_value_cents` multiplied by the rate in basis points divided by ten thousand, rounded
    half up to whole cents, and the `net_proceeds_cents` is `gross_value_cents` minus
    `penalty_cents`."

    Holding first acquired at seq 0, redeemed at fund seq 1 -> age 1 (<4) -> 300bps.
    NAV 1025 (net 3,075,000 / 3000): gross round(100*1025)=102500; penalty round(102500*0.03)=3075;
    net 99425. total_capital 3,000,000 -> 5% cap 150,000 accommodates the 102,500 gross (PRD §3.7).

    Design: Corner/calculations/penalty_tier1_under_one_year_300bps
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    # Settle 3,000,000 at par (bootstrap, shares==0) -> 3000 shares; first_acquired_seq 0.
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 3_000_000)
    settled = settle_subscription(sub["id"])
    holding_id = settled["holding_id"]
    # Valuation pegs NAV to 1025 (net 3,075,000 / 3000 shares), advancing seq to 1.
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=3_075_000, total_liabilities_cents=0)  # seq 1, NAV 1025
    rr = create_redemption_request(holding_id, 100, inv["id"])
    fulfilled = get_success_data(api.force_fulfill_redemption(rr["id"], OP))
    assert fulfilled["penalty_tier_rate_bps"] == 300
    assert fulfilled["gross_value_cents"] == 102500
    assert fulfilled["penalty_cents"] == 3075
    assert fulfilled["net_proceeds_cents"] == 99425


def test_cash_distribution_allocation_per_holding_precision(api):
    """PRD §3.6: "For each eligible holding the **gross dividend** is that holding's `shares_owned`
    multiplied by the distribution's `dividend_per_share_cents`, rounded half up to whole cents".
    PRD §3.6: "a `CASH` allocation has `drip_shares` of 0 and reinvests nothing."

    1000 shares (drip not elected) at 2.5c/share: round(1000*2.5)=2500; no DRIP minting.

    Design: Corner/calculations/cash_distribution_allocation_per_holding_precision
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000, drip_elected=False)
    settle_subscription(sub["id"])
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    dist = declare_distribution(fund["id"], period_label="2026-Q1", dividend_per_share_cents=2.5)
    paid = get_success_data(api.pay_distribution(dist["id"], OP))
    assert paid["total_paid_cents"] == 2500
    assert paid["drip_shares_minted"] == 0


def test_dividend_allocation_excludes_zero_share_holdings(api):
    """PRD §3.6: "the system creates one `DistributionAllocation` for each `Holding` in the fund's
    share classes whose `shares_owned` is positive".

    Two positive holdings (1000 and 50 shares); the 50-share one is fully redeemed to 0 before
    pay. At 2.5c/share only the remaining 1000-share holding pays: round(1000*2.5)=2500.

    Per PRD §3.1 the NAV is net assets / shares (recomputed after each settle) and gross_asset is
    moved only by a valuation, so the fund is created at gross 0 (first settle prices off the
    par-1000 bootstrap) and a peg valuation restores NAV to 1000 before the second settle. The
    second holding is sized at 50 shares so its full redemption gross (50 * 1000 = 50,000) stays
    under the 5% quarterly redemption cap (52,500 of total_capital 1,050,000, PRD §3.7).

    Design: Corner/calculations/dividend_allocation_excludes_zero_share_holdings
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=10_000)

    inv1 = create_approved_investor(annual_income_cents=500_000_000, net_worth_cents=500_000_000)
    sub1 = create_subscription(fund["id"], inv1["id"], sc["id"], 1_000_000)
    settle_subscription(sub1["id"])  # 1000 shares at par; NAV recomputes to 0/1000 = 0

    # Peg NAV back to 1000 (gross 1,000,000 / 1000 shares) before the second settle.
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=1_000_000, total_liabilities_cents=0)

    inv2 = create_approved_investor(annual_income_cents=500_000_000, net_worth_cents=500_000_000)
    sub2 = create_subscription(fund["id"], inv2["id"], sc["id"], 50_000)
    settled2 = settle_subscription(sub2["id"])  # 50 shares at NAV 1000
    holding2 = settled2["holding_id"]

    # Peg NAV to 1000 again (gross 1,050,000 / 1050 shares) so the redemption gross is 50,000.
    post_valuation(fund["id"], period_label="2026-Q2",
                   gross_asset_value_cents=1_050_000, total_liabilities_cents=0)
    # Redeem holding2 fully to 0 shares (gross 50,000 <= cap 52,500).
    rr2 = create_redemption_request(holding2, 50, inv2["id"])
    get_success_data(api.force_fulfill_redemption(rr2["id"], OP))

    dist = declare_distribution(fund["id"], period_label="2026-Q1", dividend_per_share_cents=2.5)
    paid = get_success_data(api.pay_distribution(dist["id"], OP))
    assert paid["total_paid_cents"] == 2500


# ---- Section: validations ----

def test_below_min_investment_returns_422(api):
    """PRD §3.4: "the committed amount must meet the floor: `funded_amount_cents` must be at least
    the share class's `min_investment_cents`, and a shortfall is rejected with
    `ERR_BELOW_MIN_INVESTMENT` (HTTP 422)."

    Design: Corner/validations/below_min_investment_returns_422
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    fund_v = get_success_data(api.get_fund(fund["id"], OP))["version"]
    inv_headers = make_investor_headers(inv["id"])
    res = api.create_subscription(
        {"investor_id": inv["id"], "share_class_id": sc["id"],
         "funded_amount_cents": 50_000, "expected_fund_version": fund_v}, inv_headers)
    validate_error(res, "ERR_BELOW_MIN_INVESTMENT")


def test_accreditation_required_on_settle_for_non_accredited(api):
    """PRD §3.4: "If the share class is `accredited_only`, the investor's `accredited_status` must
    be `ACCREDITED`, or the settle is rejected with `ERR_ACCREDITATION_REQUIRED` (HTTP 409)."

    Design: Corner/validations/accreditation_required_on_settle_for_non_accredited
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000, accredited_only=True)
    inv = create_approved_investor(accredited_status="NON_ACCREDITED",
                                   annual_income_cents=500_000_000, net_worth_cents=500_000_000)
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    res = api.settle_subscription(sub["id"], OP)
    validate_error(res, "ERR_ACCREDITATION_REQUIRED")


def test_duplicate_valuation_period_label_returns_409(api):
    """PRD §3.1: "identified by a `period_label` such as `2026-Q1` that must be unique within the
    fund; a duplicate label is rejected with `ERR_DUPLICATE` (HTTP 409)."

    Design: Corner/validations/duplicate_valuation_period_label_returns_409
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    sub = create_subscription(fund["id"], inv["id"], sc["id"], 1_000_000)
    settle_subscription(sub["id"])
    post_valuation(fund["id"], period_label="2026-Q1",
                   gross_asset_value_cents=1_000_000, total_liabilities_cents=0)
    res = api.create_valuation(
        fund["id"], {"period_label": "2026-Q1", "gross_asset_value_cents": 1_100_000,
                     "total_liabilities_cents": 0}, FM)
    validate_error(res, "ERR_DUPLICATE")


def test_duplicate_investor_email_returns_409(api):
    """PRD §3.3: "Registration supplies an `email` (globally unique; a duplicate is rejected with
    `ERR_DUPLICATE`)".

    Design: Corner/validations/duplicate_investor_email_returns_409
    """
    create_investor(email="dupemail@x.com", accredited_status="NON_ACCREDITED",
                    annual_income_cents=8_000_000, net_worth_cents=12_000_000)
    from test_helpers import make_anonymous_headers
    res = api.create_investor(
        {"email": "dupemail@x.com", "full_name": "Second",
         "annual_income_cents": 8_000_000, "net_worth_cents": 12_000_000}, make_anonymous_headers())
    validate_error(res, "ERR_DUPLICATE")


def test_subscription_on_closed_fund_returns_offering_not_open(api):
    """PRD §3.4: "new money is only accepted into an open offering: the parent fund must be `OPEN`
    and the targeted share class must be `OFFERING`. If either is not — for instance, the fund is
    `CLOSED_TO_NEW` or `WINDING_DOWN`, or the class is `SUSPENDED` or `CLOSED` — the create is
    rejected with `ERR_OFFERING_NOT_OPEN` (HTTP 409)."

    Design: Corner/validations/subscription_on_closed_fund_returns_offering_not_open
    """
    set_clock("2026-03-01T00:00:00Z")
    fund = create_fund(gross_asset_value_cents=0, total_liabilities_cents=0)
    sc = create_share_class(fund["id"], min_investment_cents=100_000)
    inv = create_approved_investor()
    closed = get_success_data(api.close_fund_to_new(fund["id"], FM))
    inv_headers = make_investor_headers(inv["id"])
    res = api.create_subscription(
        {"investor_id": inv["id"], "share_class_id": sc["id"],
         "funded_amount_cents": 1_000_000, "expected_fund_version": closed["version"]}, inv_headers)
    validate_error(res, "ERR_OFFERING_NOT_OPEN")
