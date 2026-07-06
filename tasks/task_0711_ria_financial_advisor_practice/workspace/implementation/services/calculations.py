"""Calculation rules (PRD §3.4, §3.6, §2.8, §3.3 / scaffold §1.3)."""

from datetime import date

from util import round_half_up

DAYS_PER_YEAR = 365
BPS_DENOMINATOR = 10000
BPS_FULL = 10000
BPS_PER_PCT = 100


# --------------------------------------------------------------------------- #
# Householding breakpoint tier (PRD §2.8)
# --------------------------------------------------------------------------- #
def tier_index(aggregated_aum_cents, tiers):
    """First tier whose upper_bound_cents is null OR strictly greater than the
    aggregate. Boundary is STRICT: aggregate == bound falls into the next tier."""
    for i, t in enumerate(tiers):
        ub = t.get("upper_bound_cents")
        if ub is None or aggregated_aum_cents < ub:
            return i
    return len(tiers) - 1 if tiers else 0


# --------------------------------------------------------------------------- #
# Tiered marginal annual fee (PRD §3.4 step 2)
# --------------------------------------------------------------------------- #
def annual_fee_cents(basis, tiers):
    """Marginal tiered fee. Round EACH tier slice independently, then sum."""
    lower = 0
    total = 0
    for t in tiers:
        ub = t.get("upper_bound_cents")
        cap = ub if ub is not None else basis
        slice_amt = max(0, min(cap, basis) - lower)
        if slice_amt > 0:
            tier_fee = round_half_up(slice_amt * t["annual_rate_bps"] / BPS_DENOMINATOR)
            total += tier_fee
        lower = cap
        if ub is None:
            break
    return total


def inclusive_day_count(period_start, period_end):
    d0 = date.fromisoformat(period_start)
    d1 = date.fromisoformat(period_end)
    return (d1 - d0).days + 1


def compute_fee(basis, tiers, minimum_annual_fee_cents, period_start, period_end):
    """Returns (gross_fee_cents, assessed_fee_cents) per PRD §3.4.

    Rounding order pinned: per-tier-slice -> sum -> prorate -> floor.
    """
    days = inclusive_day_count(period_start, period_end)
    annual = annual_fee_cents(basis, tiers)
    gross = round_half_up(annual * days / DAYS_PER_YEAR)
    min_prorated = round_half_up(minimum_annual_fee_cents * days / DAYS_PER_YEAR)
    assessed = max(gross, min_prorated)
    return gross, assessed


# --------------------------------------------------------------------------- #
# Drift evaluation (PRD §3.3)
# --------------------------------------------------------------------------- #
def drift_bps(market_value_cents, equity_value_cents, model_equity_pct):
    if market_value_cents == 0:
        actual_bps = 0
    else:
        actual_bps = round_half_up(equity_value_cents * BPS_FULL / market_value_cents)
    model_bps = model_equity_pct * BPS_PER_PCT
    return abs(actual_bps - model_bps)


# --------------------------------------------------------------------------- #
# Goal funding projection (PRD §3.6)
# --------------------------------------------------------------------------- #
def months_between(today, target_date):
    return max(0, (target_date.year - today.year) * 12 + (target_date.month - today.month))


def projected_value_cents(current_amount_cents, monthly_contribution_cents,
                          assumed_annual_return_bps, n_months):
    r = assumed_annual_return_bps / BPS_DENOMINATOR / 12  # monthly rate
    fv = current_amount_cents * ((1 + r) ** n_months)
    if r == 0:
        contrib_fv = monthly_contribution_cents * n_months
    else:
        contrib_fv = monthly_contribution_cents * (((1 + r) ** n_months - 1) / r)
    return round_half_up(fv + contrib_fv)


def funded_ratio_bps(projected_value, target_amount_cents):
    if target_amount_cents == 0:
        return 0
    return round_half_up(projected_value * BPS_FULL / target_amount_cents)
