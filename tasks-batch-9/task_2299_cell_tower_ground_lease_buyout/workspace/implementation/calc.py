"""Every algorithmic rule in the PRD, with the pinned rounding order.

Money is integer cents, rates are basis points, rounding is ROUND_HALF_UP.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

BPS = Decimal(10000)

# --- tenancy quality score -------------------------------------------------
CREDIT_POINTS = {
    "INVESTMENT_GRADE": Decimal(40),
    "CROSSOVER": Decimal(25),
    "SPECULATIVE": Decimal(10),
}
TYPE_MULTIPLIER = {"ANCHOR": Decimal("1.00"), "COLOCATION": Decimal("0.60")}
HOLDOVER_PENALTY_POINTS = Decimal(5)
SCORE_MIN = 0
SCORE_MAX = 100

# --- valuation -------------------------------------------------------------
PERPETUAL_HORIZON_YEARS = 40
RENEWAL_RISK_HAIRCUT_BPS = 2000
TERM_RISK_PREMIUM_BPS = 150
PREPAID_HAIRCUT_BPS = 500
CPI_ASSUMED_BPS = 250
MAX_BID_BPS = 10500

# --- settlement ------------------------------------------------------------
BROKER_TIER_HIGH_THRESHOLD_CENTS = 30000000
BROKER_TIER_HIGH_BPS = 150
BROKER_TIER_MID_THRESHOLD_CENTS = 10000000
BROKER_TIER_MID_BPS = 200
BROKER_TIER_LOW_BPS = 250
HOLDBACK_BPS_PER_OPEN_DISPUTE = 250
HOLDBACK_CAP_BPS = 1000

# --- portfolio posture -----------------------------------------------------
POSTURE_FROZEN_THRESHOLD_BPS = 9000
POSTURE_CONSTRAINED_THRESHOLD_BPS = 7500

# --- collateral ------------------------------------------------------------
HAIRCUT_BY_SERVICING = {
    "PERFORMING": 0,
    "WATCHLIST": 3000,
    "DELINQUENT": 5000,
    "IMPAIRED": 10000,
}

# --- amendment revenue share ----------------------------------------------
AMENDMENT_PASS_THROUGH_CAP_BPS = 2000
RENT_INCREASE_SHARE_DIVISOR = 2

# --- ceilings --------------------------------------------------------------
MAX_NEGOTIATION_ROUNDS = 3
MAX_CURE_ATTEMPTS = 3
CONSENT_VALIDITY_DAYS = 21
CURE_DEADLINE_DAYS = 30


def rhu(value, places=0):
    """Round half up to `places` decimals."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def apply_bps(amount, bps):
    """round_half_up(amount * bps / 10000) as an int."""
    return rhu_int(Decimal(amount) * Decimal(bps) / BPS)


# ---------------------------------------------------------------------------
# tenancy_quality_score
# ---------------------------------------------------------------------------

def tenancy_points(credit_tier, tenancy_type, status):
    """Returns (two_decimal_points, whole_quality_points) for one tenancy."""
    base = CREDIT_POINTS[credit_tier]
    raw = base * TYPE_MULTIPLIER[tenancy_type]
    points = rhu(raw, 2)
    if status == "HOLDOVER":
        points = points - HOLDOVER_PENALTY_POINTS
    if points < 0:
        points = Decimal(0)
    return points, int(rhu(points, 0))


def tenancy_quality_score(scored):
    """`scored` is the ordered list of two-decimal per-tenancy figures."""
    total = Decimal(0)
    for points in scored:
        total += points
    score = int(rhu(total, 0))
    if score < SCORE_MIN:
        score = SCORE_MIN
    if score > SCORE_MAX:
        score = SCORE_MAX
    return score


# ---------------------------------------------------------------------------
# stream_valuation_value / valuation_max_bid_ceiling
# ---------------------------------------------------------------------------

def discount_tier_bps(score):
    if score >= 80:
        return 700
    if score >= 60:
        return 850
    if score >= 40:
        return 1000
    return 1250


def growth_rate_bps(escalator_type, escalator_pct_bps):
    if escalator_type == "NONE":
        return 0
    if escalator_type == "FIXED_PCT":
        return escalator_pct_bps
    return min(escalator_pct_bps, CPI_ASSUMED_BPS)


def valuation_figures(method, score, annual_rent_cents, escalator_type,
                      escalator_pct_bps, remaining_term_months, prepaid_term_months):
    """Returns dict(discount_rate_bps, growth_rate_bps, horizon_years, value_cents)."""
    base_bps = discount_tier_bps(score)
    growth = growth_rate_bps(escalator_type, escalator_pct_bps)
    g = Decimal(growth) / BPS
    rent = Decimal(annual_rent_cents)

    if method == "LUMP_SUM_PERPETUAL":
        discount_bps = base_bps
        horizon_years = PERPETUAL_HORIZON_YEARS
        contracted_years = remaining_term_months // 12
        d = Decimal(discount_bps) / BPS
        total = Decimal(0)
        for year in range(1, horizon_years + 1):
            rent_y = rent * (1 + g) ** (year - 1)
            df = Decimal(1) / ((1 + d) ** year)
            pv = rent_y * df
            if year > contracted_years:
                pv = pv * (1 - Decimal(RENEWAL_RISK_HAIRCUT_BPS) / BPS)
            total += rhu(pv, 0)
        value_cents = int(total)
    else:
        effective_months = min(prepaid_term_months, remaining_term_months)
        horizon_years = effective_months // 12
        discount_bps = base_bps + TERM_RISK_PREMIUM_BPS
        d = Decimal(discount_bps) / BPS
        gross = Decimal(0)
        for year in range(1, horizon_years + 1):
            rent_y = rent * (1 + g) ** (year - 1)
            df = Decimal(1) / ((1 + d) ** year)
            gross += rhu(rent_y * df, 0)
        value_cents = rhu_int(gross * (1 - Decimal(PREPAID_HAIRCUT_BPS) / BPS))

    return {
        "discount_rate_bps": discount_bps,
        "growth_rate_bps": growth,
        "horizon_years": horizon_years,
        "value_cents": value_cents,
    }


def max_bid_cents(value_cents):
    return apply_bps(value_cents, MAX_BID_BPS)


# ---------------------------------------------------------------------------
# deal_settlement_statement
# ---------------------------------------------------------------------------

def broker_fee_bps(gross):
    if gross >= BROKER_TIER_HIGH_THRESHOLD_CENTS:
        return BROKER_TIER_HIGH_BPS
    if gross >= BROKER_TIER_MID_THRESHOLD_CENTS:
        return BROKER_TIER_MID_BPS
    return BROKER_TIER_LOW_BPS


def settlement(gross, open_dispute_count):
    """Order is pinned: tier on gross, then fee, then holdback, then net."""
    fee_bps = broker_fee_bps(gross)
    fee = apply_bps(gross, fee_bps)
    holdback_bps = min(open_dispute_count * HOLDBACK_BPS_PER_OPEN_DISPUTE, HOLDBACK_CAP_BPS)
    holdback = apply_bps(gross, holdback_bps)
    return {
        "broker_fee_bps": fee_bps,
        "broker_fee_cents": fee,
        "holdback_cents": holdback,
        "net_landowner_proceeds_cents": gross - holdback,
        "total_commitment_cents": gross + fee,
    }


# ---------------------------------------------------------------------------
# portfolio_capital_ledger
# ---------------------------------------------------------------------------

def utilization_bps(used, total_capital_cents):
    if total_capital_cents == 0:
        return 0
    return rhu_int(Decimal(used) * BPS / Decimal(total_capital_cents))


def capital_posture(util_bps):
    if util_bps >= POSTURE_FROZEN_THRESHOLD_BPS:
        return "FROZEN"
    if util_bps >= POSTURE_CONSTRAINED_THRESHOLD_BPS:
        return "CONSTRAINED"
    return "OPEN"


# ---------------------------------------------------------------------------
# pledge_eligible_value / facility_borrowing_base
# ---------------------------------------------------------------------------

def haircut_bps_for(servicing_status):
    return HAIRCUT_BY_SERVICING.get(servicing_status, 0)


def eligible_value(status, servicing_status, basis_value_cents):
    if status in ("INELIGIBLE", "RELEASED") or servicing_status == "IMPAIRED":
        return 0
    haircut = haircut_bps_for(servicing_status)
    return rhu_int(Decimal(basis_value_cents) * (1 - Decimal(haircut) / BPS))


def borrowing_base(eligible_values, concentration_limit_bps, advance_rate_bps):
    """`eligible_values` is the list of eligible_value_cents of the facility's
    PLEDGED collateral.  Returns (gross, concentration_excess, borrowing_base).

    The per-holding concentration ceiling is the gross eligible pool times
    carrier_concentration_limit_bps.  A pool made up of a single holding has no
    concentration excess (worked example: one pledge of 44627011 at the default
    5000 bps limit yields borrowing_base 29007557 = 65% of the whole pool).
    """
    gross = sum(eligible_values)
    limit_amount = apply_bps(gross, concentration_limit_bps)
    excess = 0
    if len(eligible_values) > 1:
        for value in eligible_values:
            if value > limit_amount:
                excess += value - limit_amount
    eligible_after = gross - excess
    return gross, excess, apply_bps(eligible_after, advance_rate_bps)


# ---------------------------------------------------------------------------
# amendment_revenue_share_split
# ---------------------------------------------------------------------------

def amendment_split(event_type, gross_amount_cents, pass_through_cost_cents, revenue_share_bps):
    if event_type == "AMENDMENT":
        cap = apply_bps(gross_amount_cents, AMENDMENT_PASS_THROUGH_CAP_BPS)
        effective_pass_through = min(pass_through_cost_cents, cap)
        share_bps = revenue_share_bps
    elif event_type == "RENT_INCREASE":
        effective_pass_through = 0
        share_bps = revenue_share_bps // RENT_INCREASE_SHARE_DIVISOR
    else:  # COLOCATION_ADDED
        effective_pass_through = 0
        share_bps = revenue_share_bps
    net = gross_amount_cents - effective_pass_through
    landowner = apply_bps(net, share_bps)
    return {
        "effective_pass_through_cents": effective_pass_through,
        "net_amount_cents": net,
        "share_bps_applied": share_bps,
        "landowner_share_cents": landowner,
        "acquirer_share_cents": net - landowner,
    }
