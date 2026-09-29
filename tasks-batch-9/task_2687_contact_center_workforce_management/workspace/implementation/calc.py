"""The fourteen calculations (PRD 3.2, 3.3, 3.5, 3.7, 3.8, 3.9).

Pure arithmetic only: every function here reads rows and returns numbers.
Row mutation and cascade orchestration live in cascade.py.
"""
from datetime import timedelta

from core import (
    D, q2, q4, q0, floor_int, ceil_int, clamp, DB, rows, parse_dt, parse_date,
)

# ---------------------------------------------------------------------------
# Global constants (SCAFFOLD global_constants / PRD prose)
# ---------------------------------------------------------------------------
CONFIDENCE_WEIGHT = {"HIGH": D("1.0"), "MEDIUM": D("0.6"), "LOW": D("0.3")}
MAX_EVENT_UPLIFT = D("1.50")
AHT_DRAG_COEFF = D("0.30")
AHT_CEILING_MULT = D("1.35")
REFORECAST_ALPHA = D("0.40")
REFORECAST_MULTIPLIER_FLOOR = D("0.50")
REFORECAST_MULTIPLIER_CEILING = D("2.00")
OT_TIER_1_CEILING_CENTS = 20000
OT_TIER_2_CEILING_CENTS = 60000
OT_TIER_MULTIPLIERS = {"TIER_1": D("1.50"), "TIER_2": D("1.75"), "TIER_3": D("2.00")}
SHORTFALL_PENALTY_RATE = D("0.25")
COACHING_ADHERENCE_THRESHOLD = D("0.8500")
PARTNER_PERFORMANCE_WINDOW = 3
NESTING_PRODUCTIVITY = D("0.50")

CHANNELS = ("VOICE", "CHAT", "EMAIL", "SOCIAL")


# ---------------------------------------------------------------------------
# Row navigation
# ---------------------------------------------------------------------------
def group_of(ip):
    return DB["forecast_groups"][ip["forecast_group_id"]]


def cycle_of_group(fg):
    return DB["planning_cycles"][fg["planning_cycle_id"]]


def cycle_of_interval(ip):
    return cycle_of_group(group_of(ip))


def interval_seconds(cycle):
    return int(cycle["interval_minutes"]) * 60


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap."""
    return a_start < b_end and b_start < a_end


def group_intervals(group_id):
    return [r for r in rows("interval_plans") if r["forecast_group_id"] == group_id]


def cycle_groups(cycle_id):
    return [r for r in rows("forecast_groups") if r["planning_cycle_id"] == cycle_id]


def cycle_intervals(cycle_id):
    out = []
    for fg in cycle_groups(cycle_id):
        out.extend(group_intervals(fg["id"]))
    return out


# ---------------------------------------------------------------------------
# 1. interval_volume_forecast (with the uplift set of PRD 3.3)
# ---------------------------------------------------------------------------
def in_scope_events(ip, group):
    """CONFIRMED/REALIZED drivers of the group's cycle overlapping this interval."""
    cycle_id = group["planning_cycle_id"]
    out = []
    for ev in rows("marketing_events"):
        if ev["planning_cycle_id"] != cycle_id:
            continue
        if ev["status"] not in ("CONFIRMED", "REALIZED"):
            continue
        if ev["forecast_group_id"] is not None:
            if ev["forecast_group_id"] != group["id"]:
                continue
        elif ev["channel_scope"] != group["channel"]:
            continue
        if not overlaps(ip["_start"], ip["_end"], ev["_ws"], ev["_we"]):
            continue
        out.append(ev)
    return out


def applied_event_uplift_pct(ip, group, excluded_event_ids=()):
    total = D(0)
    for ev in in_scope_events(ip, group):
        if ev["id"] in excluded_event_ids:
            continue
        total += D(ev["uplift_pct"]) * CONFIDENCE_WEIGHT[ev["confidence_tier"]]
    if total > MAX_EVENT_UPLIFT:
        total = MAX_EVENT_UPLIFT
    return q4(total)


def interval_volume_forecast(ip, group, uplift):
    curve = [D(x) for x in group["intraday_curve"]]
    curve_sum = sum(curve, D(0))
    share = curve[int(ip["interval_index"])] / curve_sum
    dow = ip["_date"].weekday()
    dow_mult = D(group["dow_multipliers"][dow])
    raw = D(group["base_daily_volume"]) * dow_mult * share
    combined = raw * (D(1) + D(uplift)) * D(group["reforecast_multiplier"])
    return q0(combined)


# ---------------------------------------------------------------------------
# 2. interval_aht_forecast
# ---------------------------------------------------------------------------
def interval_aht_forecast(group, uplift):
    base = D(group["base_aht_seconds"])
    dragged = base * (D(1) + AHT_DRAG_COEFF * D(uplift))
    ceiling = base * AHT_CEILING_MULT
    return q0(dragged if dragged < ceiling else ceiling)


# ---------------------------------------------------------------------------
# 3. staffing_requirement
# ---------------------------------------------------------------------------
def sl_uplift_band(target):
    t = D(target)
    if t >= D("0.90"):
        return D("0.35")
    if t >= D("0.80"):
        return D("0.22")
    if t >= D("0.70"):
        return D("0.12")
    return D("0.05")


def staffing_requirement(ip, group, cycle):
    """Returns (required_service_level, required_occupancy_capped, required_agents)."""
    workload = (
        D(ip["volume_forecast"]) * D(ip["aht_forecast_seconds"]) / D(interval_seconds(cycle))
    )
    shrink_complement = D(1) - D(group["shrinkage_pct"])
    uplift = sl_uplift_band(group["service_level_target_pct"])
    req_sl = ceil_int(workload * (D(1) + uplift) / shrink_complement)
    req_occ = ceil_int(workload / D(group["occupancy_target_pct"]) / shrink_complement)
    basis = cycle["requirement_basis"]
    if basis == "SERVICE_LEVEL":
        req = req_sl
    elif basis == "OCCUPANCY":
        req = req_occ
    else:
        req = max(req_sl, req_occ)
    return req_sl, req_occ, req


def coverage_of(required_agents, effective_scheduled_agents):
    gap = required_agents - effective_scheduled_agents
    if gap < 0:
        gap = 0
    return gap, ("COVERED" if gap == 0 else "SHORT")


# ---------------------------------------------------------------------------
# 4. interval_allocatable_volume
# ---------------------------------------------------------------------------
def internal_capacity_volume(ip, group, cycle, effective=None):
    eff = D(ip["effective_scheduled_agents"] if effective is None else effective)
    aht = D(ip["aht_forecast_seconds"])
    if aht == 0:
        return 0
    raw = (
        eff
        * (D(1) - D(group["shrinkage_pct"]))
        * D(group["occupancy_target_pct"])
        * D(interval_seconds(cycle))
        / aht
    )
    return floor_int(raw)


def partner_committed_volume(interval_plan_id):
    total = 0
    for al in rows("partner_allocations"):
        if al["interval_plan_id"] == interval_plan_id and al["status"] in ("COMMITTED", "SETTLED"):
            total += int(al["allocated_volume"])
    return total


# ---------------------------------------------------------------------------
# 9. partner_settlement
# ---------------------------------------------------------------------------
def line_cents(volume, rate_millicents):
    return q0(D(volume) * D(rate_millicents) / D(1000))


def partner_settlement(allocated_volume, delivered_volume, partner):
    rate = D(partner["rate_per_contact_millicents"])
    floor_cents = line_cents(allocated_volume, rate)
    delivered_cents = line_cents(delivered_volume, rate)
    shortfall_volume = int(allocated_volume) - int(delivered_volume)
    if shortfall_volume < 0:
        shortfall_volume = 0
    penalty = q0(D(shortfall_volume) * rate * SHORTFALL_PENALTY_RATE / D(1000))
    if partner["billing_basis"] == "COMMITMENT_FLOOR":
        amount = floor_cents
    else:
        amount = delivered_cents - penalty
    return floor_cents, delivered_cents, penalty, amount


# ---------------------------------------------------------------------------
# 10. overtime_cost_tiered
# ---------------------------------------------------------------------------
def ot_tier_multiplier(pre_committed_cents):
    pre = int(pre_committed_cents)
    if pre < OT_TIER_1_CEILING_CENTS:
        return OT_TIER_MULTIPLIERS["TIER_1"]
    if pre < OT_TIER_2_CEILING_CENTS:
        return OT_TIER_MULTIPLIERS["TIER_2"]
    return OT_TIER_MULTIPLIERS["TIER_3"]


def overtime_cost(hours, hourly_rate_cents, tier_multiplier, ot_premium_multiplier):
    return q0(
        D(hours) * D(hourly_rate_cents) * D(tier_multiplier) * D(ot_premium_multiplier)
    )


# ---------------------------------------------------------------------------
# 11. shift_adherence_score
# ---------------------------------------------------------------------------
def adherence_score(scheduled_seconds, out_of_adherence_seconds, excused_seconds):
    den = D(scheduled_seconds)
    if den == 0:
        return q4(0)
    num = den - D(out_of_adherence_seconds) + D(excused_seconds)
    return clamp(q4(num / den), D("0.0000"), D("1.0000")).quantize(D("0.0001"))


def shift_adherence_score(shift):
    return adherence_score(
        shift["scheduled_seconds"],
        shift["out_of_adherence_seconds"],
        shift["excused_seconds"],
    )


def shift_is_flagged(shift):
    return (
        shift["publication_status"] == "PUBLISHED"
        and shift["adherence_status"] == "OUT_OF_ADHERENCE"
        and D(shift["adherence_pct"]) < COACHING_ADHERENCE_THRESHOLD
    )


# ---------------------------------------------------------------------------
# 13. partner_rolling_performance
# ---------------------------------------------------------------------------
def rolling_sl_attainment(entries):
    window = entries[-PARTNER_PERFORMANCE_WINDOW:]
    if not window:
        return None
    total = sum((D(e["sl_attainment_pct"]) for e in window), D(0))
    return q4(total / D(len(window)))


# ---------------------------------------------------------------------------
# 14. hiring_class_ramp_fte
# ---------------------------------------------------------------------------
def hiring_class_ramp(cls, cycle):
    """Returns (expected_graduates, nesting_from, productive_from, effective_fte)."""
    expected = floor_int(D(cls["seats"]) * (D(1) - D(cls["expected_attrition_pct"])))
    start = cls["_start_date"]
    nesting_from = start + timedelta(days=7 * int(cls["training_weeks"]))
    productive_from = start + timedelta(
        days=7 * (int(cls["training_weeks"]) + int(cls["nesting_weeks"]))
    )
    horizon_end = cycle["_horizon_end"]
    if horizon_end < nesting_from:
        fte = q2(0)
    elif horizon_end < productive_from:
        fte = q2(D(expected) * NESTING_PRODUCTIVITY)
    else:
        fte = q2(D(expected))
    return expected, nesting_from, productive_from, fte
