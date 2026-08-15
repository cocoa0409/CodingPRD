"""Calculation rules (PRD section 3, SCAFFOLD section 1.3).

Rounding order is part of the contract: commissions and prorations round
per line then sum; defeasance PV is carried in full float precision and
rounded once at the end; band/threshold comparisons use integer
cross-multiplication."""
import calendar
from decimal import Decimal, ROUND_HALF_UP

from util import days_later, parse_ts, rhu, rhu_ratio

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Broker commission tiers (cents / bps)
TIER1_CAP = 1_500_000_000
TIER2_CAP = 3_000_000_000
TIER1_BPS = 200
TIER2_BPS = 150
TIER3_BPS = 100
MIN_FEE_CENTS = 25_000_000

# Deposit schedule
INITIAL_BPS = 300
ADDITIONAL_BPS = 200
MIN_DEPOSIT_CENTS = 10_000_000
INITIAL_DUE_DAYS = 3

# Retrade caps
RETRADE_ITEM_CAP_BPS = 200
RETRADE_AGGREGATE_CAP_BPS = 500

# Holdback
HOLDBACK_BPS = 50
MIN_HOLDBACK_CENTS = 1_000_000

# Loan exit
QUOTE_VALIDITY_DAYS = 10
ACCRUAL_BASIS_DAYS = 360
YM_FLOOR_BPS = 100

# Bidder qualification
QUALIFY_PCT = 25

# Recommendation hysteresis band
SELL_BAND_NUM = 105
HOLD_BAND_NUM = 95
BAND_DEN = 100

# The eight required data-room categories (any other category is rejected
# with ERR_INVALID_REQUEST). PRD section 3.3 fixes the count at eight; the
# denominator of completeness_pct is eight regardless of naming.
REQUIRED_CATEGORIES = [
    "RENT_ROLL",
    "OPERATING_STATEMENTS",
    "TITLE_COMMITMENT",
    "SURVEY",
    "ENVIRONMENTAL_REPORT",
    "LEASES",
    "TAX_BILLS",
    "SERVICE_CONTRACTS",
]

# Segregation: none of these names may collide with anything else.


# ---------------------------------------------------------------------------
# hold_sell_valuation (PRD section 3.1)
# ---------------------------------------------------------------------------


def hold_sell_valuation(asset, cap_rate_bps, discount_rate_bps, exit_cap_rate_bps,
                        hold_years, selected_method, est_sale_price_cents,
                        est_selling_costs_cents):
    noi = asset["noi_cents"]

    # DIRECT_CAP variant
    hold_value_direct_cap_cents = rhu_ratio(noi * 10000, cap_rate_bps)

    # DCF variant: NOI projected in float, no per-year rounding; single
    # round-half-up at the very end.
    n = hold_years
    g = asset["noi_growth_bps"] / 10000.0
    d = discount_rate_bps / 10000.0
    noi_y = [noi * (1.0 + g) ** y for y in range(1, n + 2)]  # y = 1..n+1
    tv = noi_y[n] * 10000.0 / exit_cap_rate_bps  # NOI_{n+1} scaled
    pv = 0.0
    for y in range(1, n + 1):
        pv += noi_y[y - 1] / (1.0 + d) ** y
    pv += tv / (1.0 + d) ** n
    hold_value_dcf_cents = int(
        Decimal(str(pv)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )

    sell_net_cents = est_sale_price_cents - est_selling_costs_cents
    if selected_method == "DIRECT_CAP":
        hold_value_cents = hold_value_direct_cap_cents
    else:
        hold_value_cents = hold_value_dcf_cents
    value_gap_cents = sell_net_cents - hold_value_cents

    # Hysteresis band, integer cross-multiplication, inclusive boundaries.
    lhs = sell_net_cents * BAND_DEN
    if lhs >= hold_value_cents * SELL_BAND_NUM:
        recommendation = "SELL"
    elif lhs <= hold_value_cents * HOLD_BAND_NUM:
        recommendation = "HOLD"
    else:
        recommendation = "MARGINAL"

    return {
        "hold_value_direct_cap_cents": hold_value_direct_cap_cents,
        "hold_value_dcf_cents": hold_value_dcf_cents,
        "hold_value_cents": hold_value_cents,
        "sell_net_cents": sell_net_cents,
        "value_gap_cents": value_gap_cents,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# bidder_qualification_threshold (PRD section 3.5)
# ---------------------------------------------------------------------------


def qualifies(proof_of_funds_cents, guidance_price_cents):
    """Inclusive 25% threshold via integer cross-multiplication."""
    return proof_of_funds_cents * 100 >= guidance_price_cents * QUALIFY_PCT


# ---------------------------------------------------------------------------
# deposit_schedule (PRD section 3.7)
# ---------------------------------------------------------------------------


def deposit_schedule(price_cents):
    initial = max(rhu_ratio(price_cents * INITIAL_BPS, 10000), MIN_DEPOSIT_CENTS)
    additional = rhu_ratio(price_cents * ADDITIONAL_BPS, 10000)
    return initial, additional


def deposit_floor(price_cents):
    """Minimum acceptable bid deposit: max(3% of price, MIN_DEPOSIT_CENTS)."""
    return max(rhu_ratio(price_cents * INITIAL_BPS, 10000), MIN_DEPOSIT_CENTS)


# ---------------------------------------------------------------------------
# retrade_cap_enforcement (PRD section 3.8)
# ---------------------------------------------------------------------------


def retrade_caps(psa, requested_reduction_cents):
    per_item_cap = rhu_ratio(psa["price_cents"] * RETRADE_ITEM_CAP_BPS, 10000)
    accepted = min(requested_reduction_cents, per_item_cap)
    aggregate_cap = rhu_ratio(
        psa["original_price_cents"] * RETRADE_AGGREGATE_CAP_BPS, 10000
    )
    allowed = (
        psa["accepted_retrade_total_cents"] + accepted <= aggregate_cap
    )
    return accepted, allowed


# ---------------------------------------------------------------------------
# broker_commission (PRD section 3.2) — per-tier rounding, then sum, then floor
# ---------------------------------------------------------------------------


def broker_commission(price_cents):
    tier1_amount = min(price_cents, TIER1_CAP)
    tier2_amount = min(max(price_cents - TIER1_CAP, 0), TIER1_CAP)
    tier3_amount = max(price_cents - TIER2_CAP, 0)
    commission = (
        rhu_ratio(tier1_amount * TIER1_BPS, 10000)
        + rhu_ratio(tier2_amount * TIER2_BPS, 10000)
        + rhu_ratio(tier3_amount * TIER3_BPS, 10000)
    )
    return max(commission, MIN_FEE_CENTS)


# ---------------------------------------------------------------------------
# accrued_interest (PRD section 3.9) — 30/360-style basis
# ---------------------------------------------------------------------------


def accrued_interest(loan_balance_cents, loan_rate_bps, accrued_days):
    raw = (
        Decimal(loan_balance_cents)
        * Decimal(loan_rate_bps)
        / Decimal(10000)
        * Decimal(accrued_days)
        / Decimal(ACCRUAL_BASIS_DAYS)
    )
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# prepayment_penalty (PRD section 3.9)
# ---------------------------------------------------------------------------


def prepayment_penalty(asset, method, reinvestment_rate_bps):
    if method == "DEFEASANCE":
        return 0
    ptype = asset["prepayment_type"]
    balance = asset["loan_balance_cents"]
    if ptype == "NONE":
        return 0
    if ptype == "STEP_DOWN":
        m = asset["remaining_term_months"]
        if m > 48:
            bps = 500
        elif m > 36:
            bps = 400
        elif m > 24:
            bps = 300
        elif m > 12:
            bps = 200
        elif m > 0:
            bps = 100
        else:
            bps = 0
        return rhu_ratio(balance * bps, 10000)
    # YIELD_MAINTENANCE
    m = asset["remaining_term_months"]
    i = reinvestment_rate_bps / 10000.0 / 12.0
    if reinvestment_rate_bps == 0:
        annuity_factor = float(m)
    else:
        annuity_factor = (1.0 - (1.0 + i) ** (-m)) / i
    raw = (
        balance
        * max(0, asset["loan_rate_bps"] - reinvestment_rate_bps)
        / 10000.0
        / 12.0
        * annuity_factor
    )
    penalty = max(
        int(Decimal(str(raw)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        rhu_ratio(balance * YM_FLOOR_BPS, 10000),
    )
    return penalty


# ---------------------------------------------------------------------------
# defeasance_cost (PRD section 3.9) — float accumulation, single rounding at
# the end, fee added after rounding
# ---------------------------------------------------------------------------


def defeasance_cost(asset, reinvestment_rate_bps):
    i = reinvestment_rate_bps / 10000.0 / 12.0
    m = asset["remaining_term_months"]
    pv = 0.0
    for t in range(1, m + 1):
        pv += asset["monthly_debt_service_cents"] / (1.0 + i) ** t
    pv += asset["loan_balance_cents"] / (1.0 + i) ** m
    cost = int(Decimal(str(pv)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cost + asset["defeasance_fee_cents"]


def loan_exit_cost(asset, method, reinvestment_rate_bps, accrued_days):
    """Compute every computed LoanPayoff field for the given inputs."""
    accrued = accrued_interest(
        asset["loan_balance_cents"], asset["loan_rate_bps"], accrued_days
    )
    if method == "PAYOFF":
        penalty = prepayment_penalty(asset, method, reinvestment_rate_bps)
        defcost = 0
        total = asset["loan_balance_cents"] + accrued + penalty
    else:
        penalty = 0
        defcost = defeasance_cost(asset, reinvestment_rate_bps)
        total = defcost
    return {
        "accrued_interest_cents": accrued,
        "prepayment_penalty_cents": penalty,
        "defeasance_cost_cents": defcost,
        "total_estimated_cost_cents": total,
    }


# ---------------------------------------------------------------------------
# proration_set (PRD section 3.10) — per-line round-half-up, then sum
# ---------------------------------------------------------------------------


def proration_set(convention, closing_date_iso, property_tax_annual_cents,
                  tax_period_start_iso, rent_monthly_cents, cam_annual_cents):
    closing = parse_ts(closing_date_iso)
    if convention == "ACTUAL_365":
        tax_start = parse_ts(tax_period_start_iso)
        # Calendar days from tax_period_start through closing_date - 1 day.
        tax_seller_days = (
            closing.date() - tax_start.date()
        ).days  # end-exclusive == through day before closing
        tax_seller_share = rhu(
            Decimal(property_tax_annual_cents) * Decimal(tax_seller_days)
            / Decimal(365)
        )
        # Calendar days from closing_date through last day of closing month.
        days_in_month = calendar.monthrange(closing.year, closing.month)[1]
        rent_buyer_days = days_in_month - closing.day + 1
        rent_buyer_share = rhu(
            Decimal(rent_monthly_cents) * Decimal(rent_buyer_days)
            / Decimal(days_in_month)
        )
        cam_buyer_days = 365 - tax_seller_days
        cam_buyer_share = rhu(
            Decimal(cam_annual_cents) * Decimal(cam_buyer_days) / Decimal(365)
        )
    else:  # BANKERS_360
        tax_start = parse_ts(tax_period_start_iso)
        full_months = (closing.year - tax_start.year) * 12 + (
            closing.month - tax_start.month
        )
        tax_seller_days = 30 * full_months + (closing.day - 1)
        tax_seller_share = rhu(
            Decimal(property_tax_annual_cents) * Decimal(tax_seller_days)
            / Decimal(360)
        )
        rent_buyer_days = 30 - closing.day + 1
        rent_buyer_share = rhu(
            Decimal(rent_monthly_cents) * Decimal(rent_buyer_days) / Decimal(30)
        )
        cam_buyer_days = 360 - tax_seller_days
        cam_buyer_share = rhu(
            Decimal(cam_annual_cents) * Decimal(cam_buyer_days) / Decimal(360)
        )
    return {
        "proration_buyer_credit_cents": tax_seller_share + rent_buyer_share,
        "proration_buyer_debit_cents": cam_buyer_share,
    }


# ---------------------------------------------------------------------------
# closing_settlement_totals (PRD section 3.10) — pinned evaluation order
# ---------------------------------------------------------------------------


def holdback_amount(price_cents):
    return max(rhu_ratio(price_cents * HOLDBACK_BPS, 10000), MIN_HOLDBACK_CENTS)


def settlement_totals(price_cents, credit_cents, debit_cents,
                      deposits_applied_cents, payoff_total_cents):
    commission = broker_commission(price_cents)
    holdback = holdback_amount(price_cents)
    buyer_due = price_cents + debit_cents - credit_cents - deposits_applied_cents
    seller_net = (
        price_cents
        + debit_cents
        - credit_cents
        - commission
        - payoff_total_cents
        - holdback
    )
    return {
        "commission_cents": commission,
        "payoff_total_cents": payoff_total_cents,
        "holdback_cents": holdback,
        "deposits_applied_cents": deposits_applied_cents,
        "buyer_due_cents": buyer_due,
        "seller_net_cents": seller_net,
    }
