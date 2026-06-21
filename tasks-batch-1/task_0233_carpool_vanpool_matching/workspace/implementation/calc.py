"""Calculation rules (PRD §3.7, §3.8, §3.9, §3.4, §3.5).

All money is integer cents. Percentages are fractions preserved at input
precision. Rounding is round-half-up; the per-formula evaluation order is
pinned exactly as the PRD specifies.
"""
from decimal import Decimal, ROUND_HALF_UP


def _D(x):
    return Decimal(str(x))


def round_half_up_cents(value):
    """Round a Decimal/number to the nearest whole cent, half-up."""
    return int(_D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round to one decimal place, half-up; returns float."""
    return float(_D(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---- trip_total_cost (PRD §3.5) -----------------------------------------
def trip_total_cost(base_cost_cents, per_mile_cents, distance_miles):
    # The single per-mile product is rounded half-up to the nearest whole cent
    # BEFORE the base is added.
    per_mile_part = round_half_up_cents(_D(per_mile_cents) * _D(distance_miles))
    return int(base_cost_cents) + per_mile_part


# ---- cost_share (PRD §3.7) ----------------------------------------------
def _tier_factor(n):
    if n >= 4:
        return Decimal("0.80")
    if n == 3:
        return Decimal("0.90")
    return Decimal("1.00")


def cost_share(total_cost_cents, n_seats, this_seat_count):
    """Per-reservation cost-share.

    EVALUATION ORDER (pinned): derive tier factor from N, then divide by N,
    then multiply by this seat_count, then round ONCE. Never round the
    per-seat raw before multiplying by seat_count.
    """
    if n_seats <= 0:
        return 0
    tf = _tier_factor(n_seats)
    per_seat_raw = (_D(total_cost_cents) * tf) / _D(n_seats)
    return round_half_up_cents(per_seat_raw * _D(this_seat_count))


# ---- subsidy (PRD §3.7) -------------------------------------------------
def subsidy(cs, hov_lane_used, hov_discount_pct, employer_match_pct,
            month_remaining, program_status, subsidy_consumed_cents,
            subsidy_budget_cents):
    """Subsidy waterfall over a single rider cost-share.

    Per-layer rounding (mode-b): round each layer to cents first, THEN sum.
    """
    if hov_lane_used:
        hov_part = round_half_up_cents(_D(cs) * _D(hov_discount_pct))
    else:
        hov_part = 0
    match_part = round_half_up_cents(_D(cs - hov_part) * _D(employer_match_pct))
    raw_subsidy = hov_part + match_part
    # Monthly cap waterfall: smallest of raw, remaining monthly benefit, and cs.
    applied = min(raw_subsidy, max(0, month_remaining), cs)
    # Program-budget guard: frozen program or budget overrun collapses to 0.
    if program_status == "FROZEN":
        return 0
    if subsidy_consumed_cents + applied > subsidy_budget_cents:
        return 0
    return applied


# ---- reliability_score (PRD §3.8) ---------------------------------------
EVENT_WEIGHT = {
    "COMPLETION": Decimal("2.0"),
    "NO_SHOW": Decimal("-15.0"),
    "LATE_CANCEL": Decimal("-6.0"),
    "GRH_OVERUSE": Decimal("-4.0"),
}


def reliability_score(weight_deltas, provisional_pending=0):
    """raw = 100 + sum(weight_delta) [+ 2.0 * pending]; clamp then round 1dp."""
    raw = Decimal("100")
    for d in weight_deltas:
        raw += _D(d)
    raw += _D(provisional_pending) * Decimal("2.0")
    raw = max(Decimal("0.0"), min(Decimal("100.0"), raw))
    return round_half_up_1dp(raw)


# ---- grh_reimbursement (PRD §3.9) ---------------------------------------
def grh_reimbursement(claimed_fare_cents, per_event_cap_cents, annual_remaining):
    return min(int(claimed_fare_cents), int(per_event_cap_cents), max(0, annual_remaining))


# ---- match_score (PRD §3.4) ---------------------------------------------
def match_score(needed_days_count, seat_room, driver_reliability_score):
    value = (Decimal("10.0") * _D(needed_days_count)
             + Decimal("1.0") * _D(seat_room)
             + Decimal("0.05") * _D(driver_reliability_score))
    return float(_D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
