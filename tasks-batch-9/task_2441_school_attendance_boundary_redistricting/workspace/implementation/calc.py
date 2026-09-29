"""The eleven calculations of PRD section 3, as pure functions over Decimal.

Rounding order is deliberately non-uniform across this module (PRD 2.6):
 - enrollment projection rounds every per-development contribution BEFORE summing;
 - transportation cost accumulates unrounded and rounds the scenario total once;
 - rolling absorption carries rates and overlaps unrounded and rounds only the peak.
"""

import math
from decimal import Decimal

from core import dec, round_half_up

# --- constants (SCAFFOLD 1.4 constants / PRD 3.x prose) -------------------
COHORT_SURVIVAL_RATE = Decimal("0.98")
UNIT_YIELD = {
    "SINGLE_FAMILY": Decimal("0.42"),
    "TOWNHOME": Decimal("0.25"),
    "MULTI_FAMILY": Decimal("0.13"),
}
ENTITLEMENT_WEIGHT = {
    "PROPOSED": Decimal("0.25"),
    "ENTITLED": Decimal("0.60"),
    "PERMITTED": Decimal("0.85"),
    "UNDER_CONSTRUCTION": Decimal("1.00"),
    "COMPLETE": Decimal("1.00"),
    "WITHDRAWN": Decimal("0.00"),
}
DEVELOPMENT_FRL_RATE = {
    "SINGLE_FAMILY": Decimal("0.18"),
    "TOWNHOME": Decimal("0.32"),
    "MULTI_FAMILY": Decimal("0.54"),
}
DAYS_PER_YEAR = 365
DAYS_PER_MONTH = 30
SECONDS_PER_MONTH = DAYS_PER_MONTH * 86400
ROLLING_ABSORPTION_WINDOW_MONTHS = 12
CRITICAL_UTILIZATION_PCT = Decimal("110.00")
SUPERMAJORITY_TRIGGER_PCT = Decimal("15.00")
BUS_CAPACITY = 71
DAILY_BUS_BASE_USD = Decimal("95.00")
PER_MINUTE_USD = Decimal("1.85")
MIN_BILLED_MINUTES = Decimal("15")
SCHOOL_DAYS_PER_YEAR = Decimal("180")
WALK_LIMIT_MILES = {
    "ELEMENTARY": Decimal("1.0"),
    "MIDDLE": Decimal("1.5"),
    "HIGH": Decimal("2.0"),
}
MAX_RIDE_MINUTES = {"ELEMENTARY": Decimal("45"), "MIDDLE": Decimal("55"), "HIGH": Decimal("60")}
WATCH_MULTIPLIER = Decimal("2")
MIN_ACTIVE_SCHOOLS = 2
MIN_PLANNING_AREAS = 3
MIN_REGIME_GAP_YEARS = 2


# --------------------------------------------------------------------------
# 1. area_rolling_absorption (PRD 3.2)
# --------------------------------------------------------------------------
def absorption_peak(candidates):
    """candidates: list of dicts with first_occupancy_dt, buildout_months,
    total_units, in creation order. Returns the peak rounded half up to 2 dp."""
    if not candidates:
        return Decimal("0.00")
    windows = []
    for cand in candidates:
        start = cand["first_occupancy_dt"]
        months = dec(cand["buildout_months"])
        end = start + _months_delta(cand["buildout_months"])
        rate = dec(cand["total_units"]) / months  # units per 30-day month, unrounded
        windows.append((start, end, rate))

    probe_starts = []
    seen = set()
    for cand in candidates:  # creation order, so ties keep creation order
        start = cand["first_occupancy_dt"]
        if start not in seen:
            seen.add(start)
            probe_starts.append(start)
    probe_starts.sort()

    peak = Decimal(0)
    for probe_start in probe_starts:
        probe_end = probe_start + _months_delta(ROLLING_ABSORPTION_WINDOW_MONTHS)
        total = Decimal(0)
        for start, end, rate in windows:
            lo = max(start, probe_start)
            hi = min(end, probe_end)
            if hi <= lo:
                continue
            overlap_months = dec((hi - lo).total_seconds()) / dec(SECONDS_PER_MONTH)
            total += rate * overlap_months
        if total > peak:
            peak = total
    return round_half_up(peak, 2)


def _months_delta(months):
    from datetime import timedelta
    return timedelta(days=DAYS_PER_MONTH * int(months))


# --------------------------------------------------------------------------
# 2. area_enrollment_projection (PRD 3.3)
# --------------------------------------------------------------------------
def admitted_developments(developments, variant):
    """Developments admitted by a run variant, in creation order."""
    out = []
    for dev in developments:
        status = dev["entitlement_status"]
        if variant == "COHORT_SURVIVAL":
            if status in ("UNDER_CONSTRUCTION", "COMPLETE"):
                out.append(dev)
        else:
            if status != "WITHDRAWN":
                out.append(dev)
    return out


def development_contribution(dev, variant, horizon_end, first_occupancy_dt):
    """The per-development contribution, rounded half up to 2 dp per PRD 3.3."""
    if variant == "COHORT_SURVIVAL":
        weight = Decimal("1.00")
        occupancy = Decimal("1.00")
    else:
        weight = ENTITLEMENT_WEIGHT[dev["entitlement_status"]]
        elapsed_seconds = (horizon_end - first_occupancy_dt).total_seconds()
        whole_months = int(elapsed_seconds // SECONDS_PER_MONTH)
        occupancy = dec(whole_months) / dec(dev["buildout_months"])
        if occupancy < 0:
            occupancy = Decimal("0.0")
        elif occupancy > 1:
            occupancy = Decimal("1.0")
    override = dev.get("student_yield_override")
    per_unit = dec(override) if override is not None else UNIT_YIELD[dev["unit_type"]]
    raw = dec(dev["total_units"]) * per_unit * weight * occupancy
    return round_half_up(raw, 2)


def base_students(resident_student_count, horizon_years):
    raw = dec(resident_student_count) * (COHORT_SURVIVAL_RATE ** int(horizon_years))
    return int(round_half_up(raw, 0))


# --------------------------------------------------------------------------
# 3. school_capacity_utilization (PRD 3.5)
# --------------------------------------------------------------------------
def utilization_pct(load, effective_capacity):
    if effective_capacity == 0:
        return None
    return round_half_up(dec(100) * dec(load) / dec(effective_capacity), 2)


def utilization_band(util, low_pct, high_pct):
    util = dec(util)
    if util >= CRITICAL_UTILIZATION_PCT:
        return "CRITICAL"
    if util < dec(low_pct):
        return "UNDER"
    if util <= dec(high_pct):
        return "IN_TARGET"
    return "OVER"


# --------------------------------------------------------------------------
# 4. transportation_cost_annual (PRD 3.5)
# --------------------------------------------------------------------------
def walk_eligible(option, level):
    return (
        dec(option["walk_distance_miles"]) <= WALK_LIMIT_MILES[level]
        and bool(option["has_safe_route"])
    )


def assignment_transport_cost(riders, bus_minutes):
    """Unrounded per-assignment cost."""
    billed = max(dec(bus_minutes), MIN_BILLED_MINUTES)
    buses = math.ceil(riders / BUS_CAPACITY) if riders > 0 else 0
    return dec(buses) * (DAILY_BUS_BASE_USD + PER_MINUTE_USD * billed) * SCHOOL_DAYS_PER_YEAR


# --------------------------------------------------------------------------
# 5. board_vote_outcome (PRD 3.7)
# --------------------------------------------------------------------------
def quorum_threshold(board_member_count):
    return -(-int(board_member_count) // 2)  # ceil


def quorum_met(votes_for, votes_against, votes_abstain, board_member_count):
    cast = int(votes_for) + int(votes_against) + int(votes_abstain)
    return cast >= quorum_threshold(board_member_count)


def supermajority_required(students_reassigned_pct):
    return dec(students_reassigned_pct) > SUPERMAJORITY_TRIGGER_PCT


def majority_met(votes_for, votes_against, needs_supermajority):
    vf = int(votes_for)
    denominator = vf + int(votes_against)
    if needs_supermajority:
        return 3 * vf >= 2 * denominator
    return 2 * vf > denominator


# --------------------------------------------------------------------------
# 6. transfer_seat_pool (PRD 3.8)
# --------------------------------------------------------------------------
def seat_pool(effective_capacity, transfer_cap_pct, head_count):
    allowance = (dec(effective_capacity) * dec(transfer_cap_pct)) / dec(100)
    seats = int(allowance.to_integral_value(rounding="ROUND_FLOOR"))
    return seats - int(head_count)


# --------------------------------------------------------------------------
# 7. enrollment_variance_flag (PRD 3.9)
# --------------------------------------------------------------------------
def variance_pct(observed, projected):
    return round_half_up(dec(100) * (dec(observed) - dec(projected)) / dec(projected), 2)


def variance_flag(var_pct, tolerance_pct):
    magnitude = abs(dec(var_pct))
    tolerance = dec(tolerance_pct)
    if magnitude <= tolerance:
        return "WITHIN_TOLERANCE"
    if magnitude <= tolerance * WATCH_MULTIPLIER:
        return "WATCH"
    return "CORRECTIVE_ACTION_REQUIRED"


# --------------------------------------------------------------------------
# 8. regime_window_overlap (PRD 3.7)
# --------------------------------------------------------------------------
def regime_conflicts(cand_start, cand_years, other_start, other_years):
    cand_end = cand_start + cand_years        # half open [start, end)
    other_end = other_start + other_years
    if cand_start < other_end and other_start < cand_end:
        return True
    # Disjoint: the later interval must begin at least 2 school years after the
    # earlier one ends.
    if cand_start >= other_end:
        return (cand_start - other_end) < MIN_REGIME_GAP_YEARS
    return (other_start - cand_end) < MIN_REGIME_GAP_YEARS


# --------------------------------------------------------------------------
# 9. contiguity_evaluation (PRD 3.5)
# --------------------------------------------------------------------------
def is_contiguous(member_ids_in_order, adjacency):
    """member_ids_in_order: the school's assigned areas ordered by created_at ASC.
    adjacency: dict area_id -> set of neighbour ids (symmetric)."""
    if not member_ids_in_order:
        return True
    members = set(member_ids_in_order)
    start = member_ids_in_order[0]
    seen = {start}
    queue = [start]
    while queue:
        current = queue.pop(0)
        for neighbour in adjacency.get(current, ()):  # follow only in-set edges
            if neighbour in members and neighbour not in seen:
                seen.add(neighbour)
                queue.append(neighbour)
    return len(seen) == len(members)


# --------------------------------------------------------------------------
# 10. demographic_impact_index (PRD 3.5)
# --------------------------------------------------------------------------
def dissimilarity_index(per_school_tallies, frl_total, nonfrl_total):
    if frl_total == 0 or nonfrl_total == 0:
        return Decimal("0.0000")
    accumulator = Decimal(0)
    for frl_part, nonfrl_part in per_school_tallies:
        accumulator += abs(dec(frl_part) / dec(frl_total) - dec(nonfrl_part) / dec(nonfrl_total))
    return round_half_up(accumulator / dec(2), 4)


# --------------------------------------------------------------------------
# 11. transfer_eligibility_resolution (PRD 3.8)
# --------------------------------------------------------------------------
def resolve_eligibility(rules, student_grade, reason, sibling_ok, effective_school_year):
    """Walk the four rungs in order and stop at the first match. Returns
    (resolved_reason, consumes_seat_pool)."""

    def covers(rule_type):
        for rule in rules:
            if rule["rule_type"] != rule_type:
                continue
            if rule["grade_low"] <= student_grade <= rule["grade_high"] and \
                    rule["sunset_school_year"] >= effective_school_year:
                return True
        return False

    if covers("TERMINAL_GRADE_GRANDFATHER"):
        return "TERMINAL_GRADE_GRANDFATHER", False
    if reason == "SIBLING" and sibling_ok and covers("SIBLING_LINK"):
        return "SIBLING_LINK", True
    if covers("PHASE_IN_GRADE_BAND"):
        return "PHASE_IN_GRADE_BAND", False
    if reason == "HARDSHIP":
        return "HARDSHIP_REVIEW", True
    return "NONE", False
