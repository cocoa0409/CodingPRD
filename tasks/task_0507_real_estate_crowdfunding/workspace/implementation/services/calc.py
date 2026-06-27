"""Calculation rules (§1.3 / PRD §2.7, §3). All money in integer cents; shares to 4 dp.

Rounding is always ROUND_HALF_UP (PRD §2.7).
"""
from decimal import Decimal, ROUND_HALF_UP

# Constants (§1.3)
PAR_NAV_CENTS = 1000
ACH_RATE = Decimal("0.008")
ACH_MIN_FEE_CENTS = 100
LARGE_INVESTOR_THRESHOLD_CENTS = 2500000
NON_ACCREDITED_RATE = Decimal("0.10")
QUARTERLY_REDEMPTION_CAP_RATE = Decimal("0.05")

TIER1_RATE_BPS = 300
TIER2_RATE_BPS = 200
TIER3_RATE_BPS = 100
TIER4_RATE_BPS = 0
TIER1_MAX_Q = 4
TIER2_MAX_Q = 8
TIER3_MAX_Q = 12

CENT = Decimal("1")
SHARE_Q = Decimal("0.0001")


def round_cents(value):
    """Round half up to whole cents -> int."""
    return int(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def round_shares(value):
    """Round half up to 4 dp -> Decimal."""
    return Decimal(value).quantize(SHARE_Q, rounding=ROUND_HALF_UP)


def to_dec(value):
    return Decimal(str(value))


# ---- nav_per_share ----
def nav_per_share(gross_asset_value_cents, total_liabilities_cents, shares_outstanding):
    net_cents = gross_asset_value_cents - total_liabilities_cents
    shares = to_dec(shares_outstanding)
    if shares == 0:
        return PAR_NAV_CENTS
    return round_cents(Decimal(net_cents) / shares)


# ---- fund_shares_outstanding ----
def fund_shares_outstanding(holdings_in_fund):
    """Sum shares_owned over holdings with positive balance, rounded half up to 4 dp."""
    total = Decimal("0")
    for h in holdings_in_fund:
        owned = to_dec(h["shares_owned"])
        if owned > 0:
            total += owned
    return round_shares(total)


# ---- subscription_shares (provisional + final share count) ----
def subscription_shares(funded_amount_cents, nav_used_cents):
    return round_shares(Decimal(funded_amount_cents) / Decimal(nav_used_cents))


# ---- ach_fee (pinned evaluation order) ----
def ach_fee(funded_amount_cents):
    ach_fee_raw = max(
        ACH_MIN_FEE_CENTS,
        round_cents(Decimal(funded_amount_cents) * ACH_RATE),
    )
    prelim_total = funded_amount_cents + ach_fee_raw
    if prelim_total >= LARGE_INVESTOR_THRESHOLD_CENTS:
        ach_fee_cents = 0
    else:
        ach_fee_cents = ach_fee_raw
    total_charged_cents = funded_amount_cents + ach_fee_cents
    return ach_fee_cents, total_charged_cents


# ---- suitability_cap ----
def suitability_cap(annual_income_cents, net_worth_cents):
    base = max(annual_income_cents, net_worth_cents)
    return round_cents(NON_ACCREDITED_RATE * Decimal(base))


# ---- penalty_age_quarters ----
def penalty_age_quarters(current_valuation_seq, first_acquired_seq):
    return current_valuation_seq - first_acquired_seq


# ---- early_withdrawal_penalty ----
def penalty_tier_rate_bps(age_quarters):
    if age_quarters < TIER1_MAX_Q:
        return TIER1_RATE_BPS
    elif age_quarters < TIER2_MAX_Q:
        return TIER2_RATE_BPS
    elif age_quarters < TIER3_MAX_Q:
        return TIER3_RATE_BPS
    else:
        return TIER4_RATE_BPS


def gross_value(shares_requested, nav_per_share_cents):
    return round_cents(to_dec(shares_requested) * Decimal(nav_per_share_cents))


def penalty_amount(gross_value_cents, rate_bps):
    return round_cents(Decimal(gross_value_cents) * Decimal(rate_bps) / Decimal(10000))


# ---- dividend_allocation: per-holding gross dividend ----
def gross_dividend(shares_owned, dividend_per_share_cents):
    return round_cents(to_dec(shares_owned) * to_dec(dividend_per_share_cents))


def drip_shares(gross_dividend_cents, nav_per_share_cents):
    if nav_per_share_cents == 0:
        # NAV is zero (net assets zero): no shares can be priced; reinvest nothing.
        return round_shares(0)
    return round_shares(Decimal(gross_dividend_cents) / Decimal(nav_per_share_cents))


# ---- redemption_cap ----
def redemption_cap(total_capital_cents):
    return round_cents(QUARTERLY_REDEMPTION_CAP_RATE * Decimal(total_capital_cents))
