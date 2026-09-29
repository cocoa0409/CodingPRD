"""Derived aggregates, calculations, selectors and cascades.

Constants and formulas are transcribed from SCAFFOLD.yaml `calculations` and
PRD.md §2.5 / §2.8 / §2.9 / §3.x.
"""

import math
from decimal import Decimal
from fractions import Fraction

from core import (
    ApiError,
    clock_date,
    clock_dt,
    clock_raw,
    db,
    parse_dt,
    q,
    qi,
    touch,
)


def parse_window(value, field):
    """Priority 11 — time-window well-formedness."""
    parsed = parse_dt(value)
    if parsed is None:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "Field '%s' must be a parseable RFC 3339 UTC instant." % field,
        )
    return parsed


def require_ordered(start_dt, end_dt):
    if not end_dt > start_dt:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "The window end must be strictly after the window start.",
        )

# ---- calculation constants -------------------------------------------------

AUTOMATION_TIER_HIGH_PCT = Decimal("85")
AUTOMATION_TIER_MID_PCT = Decimal("60")
PPH_TIER_HIGH = 1200
PPH_TIER_MID = 950
PPH_TIER_LOW = 700
POSTURE_MULTIPLIER = {
    "OPEN": Fraction(1, 1),
    "RESTRICTED": Fraction(11, 10),
    "FROZEN": Fraction(5, 4),
}
MIN_HEADCOUNT_PER_LINE = 4

RATE_CENTS_PER_HOUR = {"CORE": 2150, "SEASONAL": 1875, "FLEX": 2480}
FLEX_PREMIUM_TIER_1_MAX_RATIO = Fraction(20, 100)
FLEX_PREMIUM_TIER_2_MAX_RATIO = Fraction(35, 100)
FLEX_PREMIUM_PCT = {
    "TIER_1": Fraction(0, 1),
    "TIER_2": Fraction(5, 100),
    "TIER_3": Fraction(12, 100),
}

AT_RISK_GAP_THRESHOLD = 0
MAX_LINE_HEADCOUNT = 22
MAX_CONSECUTIVE_SHIFTS = 5
REQUIRED_TRAINING_SESSIONS = 2
JAM_RETRY_LIMIT = 3

FIXED_OVERHEAD_CENTS_PER_SHIFT = 12000
REWORK_CENTS_PER_MISSORT_PACKAGE = 35

TENURE_BUCKET_RISK = {
    "D0_14": Fraction(42, 100),
    "D15_45": Fraction(31, 100),
    "D46_120": Fraction(18, 100),
    "D121_PLUS": Fraction(9, 100),
}
HIRE_CLASS_ATTRITION_ADJ = {
    "CORE": Fraction(0, 1),
    "SEASONAL": Fraction(12, 100),
    "FLEX": Fraction(7, 100),
}
NO_SHOW_WEIGHT = Fraction(6, 100)
MISSED_TRAINING_WEIGHT = Fraction(5, 100)
CERTIFIED_CREDIT = Fraction(4, 100)
MIN_OBSERVATION_ASSIGNMENTS = 3
ATTRITION_FLAG_THRESHOLD = Decimal("0.55")
SCORE_CEILING = Fraction(95, 100)
SCORE_FLOOR = Fraction(2, 100)

CUFT_PER_PACKAGE = {
    "SMALL": Decimal("0.335"),
    "MEDIUM": Decimal("1.205"),
    "LARGE": Decimal("3.755"),
    "OVERSIZED": Decimal("11.505"),
}

PRIORITY_CLASS_RANK = {"CRITICAL": 0, "EXPRESS": 1, "STANDARD": 2, "DEFERRED": 3}

JAM_FREEZE_THRESHOLD = 3
LANE_PRESSURE_RESTRICT_RATIO = Decimal("1.50")
AUTOMATION_RESTRICT_PCT = Decimal("45")

CAPACITY_FLOOR = 1


# ---- collection helpers ---------------------------------------------------


def chutes_of(center_id):
    return [c for c in db.sort_chutes.values() if c["sort_center_id"] == center_id]


def lanes_of(center_id):
    return [l for l in db.destination_lanes.values() if l["sort_center_id"] == center_id]


def doors_of(center_id):
    return [d for d in db.dock_doors.values() if d["sort_center_id"] == center_id]


def appointments_of(center_id):
    return [a for a in db.trailer_appointments.values() if a["sort_center_id"] == center_id]


def plans_of(center_id):
    return [p for p in db.shift_plans.values() if p["sort_center_id"] == center_id]


def assignments_of_plan(plan_id):
    return [a for a in db.staff_assignments.values() if a["shift_plan_id"] == plan_id]


def assignments_of_worker(worker_id):
    return [a for a in db.staff_assignments.values() if a["worker_id"] == worker_id]


def chute_assignments_of_chute(chute_id):
    return [a for a in db.chute_assignments.values() if a["chute_id"] == chute_id]


def chute_assignments_of_lane(lane_id):
    return [a for a in db.chute_assignments.values() if a["destination_lane_id"] == lane_id]


def line_count(center_id):
    """PRD §3.4 step 3 — chutes whose status is ACTIVE or CONGESTED."""
    return len([c for c in chutes_of(center_id) if c["status"] in ("ACTIVE", "CONGESTED")])


def center_of_chute(chute):
    return db.sort_centers.get(chute["sort_center_id"])


# ---- calculation: lane_pressure ------------------------------------------


def recompute_lane(lane):
    """assigned_capacity_pph + lane_pressure_ratio. Returns True when changed."""
    chute_ids = set()
    for assignment in chute_assignments_of_lane(lane["id"]):
        if assignment["status"] == "ACTIVE":
            chute_ids.add(assignment["chute_id"])
    capacity = 0
    for chute_id in chute_ids:
        chute = db.sort_chutes.get(chute_id)
        if chute is not None:
            capacity += chute["throughput_pph"]
    divisor = capacity if capacity > CAPACITY_FLOOR else CAPACITY_FLOOR
    ratio = q(Fraction(lane["backlog_package_count"], divisor), 4)
    changed = (capacity != lane["assigned_capacity_pph"]) or (ratio != lane["lane_pressure_ratio"])
    lane["assigned_capacity_pph"] = capacity
    lane["lane_pressure_ratio"] = ratio
    return changed


def recompute_lane_and_touch(lane):
    if recompute_lane(lane):
        touch(lane)


# ---- calculation: ops_posture_derivation ---------------------------------


def derive_posture(center):
    open_jam = len([a for a in appointments_of(center["id"]) if a["status"] == "JAM_HELD"])
    open_serious = len(
        [
            r
            for r in db.injury_reports.values()
            if r["sort_center_id"] == center["id"]
            and r["severity"] == "SERIOUS"
            and r["status"] == "OPEN"
        ]
    )
    active_lanes = [l for l in lanes_of(center["id"]) if l["status"] == "ACTIVE"]
    if active_lanes:
        max_pressure = max(l["lane_pressure_ratio"] for l in active_lanes)
    else:
        max_pressure = Decimal("0")
    if open_serious >= 1 or open_jam >= JAM_FREEZE_THRESHOLD:
        posture = "FROZEN"
    elif (
        open_jam >= 1
        or max_pressure >= LANE_PRESSURE_RESTRICT_RATIO
        or center["automation_utilization_pct"] < AUTOMATION_RESTRICT_PCT
    ):
        posture = "RESTRICTED"
    else:
        posture = "OPEN"
    return posture, open_jam, open_serious


def recompute_center_posture(center):
    """Refresh the derived counters and re-derive ops_posture (PRD §2.5)."""
    posture, open_jam, open_serious = derive_posture(center)
    if center["open_jam_count"] != open_jam:
        center["open_jam_count"] = open_jam
        touch(center)
    if center["open_serious_injury_count"] != open_serious:
        center["open_serious_injury_count"] = open_serious
        touch(center)
    if center["ops_posture"] != posture:
        center["ops_posture"] = posture
        center["last_posture_change_at"] = clock_raw()
        touch(center)


def require_not_frozen(center):
    if center["ops_posture"] == "FROZEN":
        raise ApiError("ERR_CENTER_FROZEN")


# ---- calculation: unload_sequence_ranking --------------------------------


def rerank_arrived(center_id):
    candidates = [a for a in appointments_of(center_id) if a["status"] == "ARRIVED"]
    candidates.sort(
        key=lambda a: (
            PRIORITY_CLASS_RANK[a["priority_class"]],
            a["_window_start"],
            -a["manifest_package_count"],
            a["_seq"],
        )
    )
    for index, appointment in enumerate(candidates, start=1):
        if appointment["unload_sequence_rank"] != index:
            appointment["unload_sequence_rank"] = index
            touch(appointment)


# ---- calculation: door_interval_conflict ---------------------------------

LIVE_APPOINTMENT_STATES = ("SCHEDULED", "ARRIVED", "UNLOADING", "JAM_HELD")


def door_window_conflict(door, new_start, new_end):
    buffer_seconds = door["turnaround_buffer_min"] * 60
    for existing in db.trailer_appointments.values():
        if existing["door_id"] != door["id"]:
            continue
        if existing["status"] not in LIVE_APPOINTMENT_STATES:
            continue
        e_start = existing["_window_start"]
        e_end = existing["_window_end"]
        if (new_start - e_end).total_seconds() < buffer_seconds and (
            e_start - new_end
        ).total_seconds() < buffer_seconds:
            return True
    return False


# ---- calculation: chute_concurrency_capacity ----------------------------


def chute_concurrency_exceeded(chute, new_start, new_end, excluded_ids):
    existing = [
        a
        for a in chute_assignments_of_chute(chute["id"])
        if a["status"] in ("ACTIVE", "SUSPENDED") and a["id"] not in excluded_ids
    ]
    overlapping = [
        a
        for a in existing
        if new_start < a["_window_end"] and a["_window_start"] < new_end
    ]
    instants = [new_start]
    for assignment in overlapping:
        start = assignment["_window_start"]
        if new_start <= start < new_end:
            instants.append(start)
    peak = 0
    for instant in instants:
        count = len(
            [a for a in overlapping if a["_window_start"] <= instant < a["_window_end"]]
        )
        if count > peak:
            peak = count
    return (1 + peak) > chute["max_concurrent_destinations"]


# ---- calculation: required_headcount ------------------------------------


def base_pph_per_associate(center):
    automation = center["automation_utilization_pct"]
    if automation >= AUTOMATION_TIER_HIGH_PCT:
        return PPH_TIER_HIGH
    if automation >= AUTOMATION_TIER_MID_PCT:
        return PPH_TIER_MID
    return PPH_TIER_LOW


def calc_required_headcount(plan, center):
    shift_hours = plan["shift_hours"]
    base_pph = base_pph_per_associate(center)
    lines = line_count(center["id"])
    if shift_hours <= 0:
        raw = Fraction(0, 1)
    else:
        raw = Fraction(plan["forecast_volume"]) / (Fraction(base_pph) * Fraction(shift_hours))
    posture_adjusted = raw * POSTURE_MULTIPLIER[center["ops_posture"]]
    return max(MIN_HEADCOUNT_PER_LINE * lines, math.ceil(posture_adjusted))


def calc_shift_hours(start_dt, end_dt):
    seconds = Fraction(int((end_dt - start_dt).total_seconds()))
    return q(seconds / 3600, 2)


# ---- calculation: planned_labor_cost ------------------------------------


def flex_premium_pct(ratio):
    if ratio < FLEX_PREMIUM_TIER_1_MAX_RATIO:
        return FLEX_PREMIUM_PCT["TIER_1"]
    if ratio < FLEX_PREMIUM_TIER_2_MAX_RATIO:
        return FLEX_PREMIUM_PCT["TIER_2"]
    return FLEX_PREMIUM_PCT["TIER_3"]


def calc_planned_labor_cents(plan, flex_draw):
    shift_hours = Fraction(plan["shift_hours"])
    core = plan["planned_core_headcount"]
    seasonal = plan["planned_seasonal_headcount"]
    base_cents = (
        qi(Fraction(core) * shift_hours * RATE_CENTS_PER_HOUR["CORE"])
        + qi(Fraction(seasonal) * shift_hours * RATE_CENTS_PER_HOUR["SEASONAL"])
        + qi(Fraction(flex_draw) * shift_hours * RATE_CENTS_PER_HOUR["FLEX"])
    )
    total_headcount = core + seasonal + flex_draw
    if total_headcount == 0:
        ratio = Fraction(0, 1)
    else:
        ratio = Fraction(flex_draw, total_headcount)
    premium = flex_premium_pct(ratio)
    return qi(Fraction(base_cents) * (1 + premium))


# ---- calculation: actual_labor_cost -------------------------------------


def calc_actual_labor_cents(plan):
    completed = [a for a in assignments_of_plan(plan["id"]) if a["status"] == "COMPLETED"]
    completed.sort(key=lambda a: a["_seq"])
    base_cents = 0
    flex_rows = 0
    for assignment in completed:
        worker = db.workers.get(assignment["worker_id"])
        hire_class = worker["hire_class"] if worker else "CORE"
        base_cents += qi(Fraction(assignment["worked_hours"]) * RATE_CENTS_PER_HOUR[hire_class])
        if hire_class == "FLEX":
            flex_rows += 1
    flex_draw = plan["flex_draw_count"]
    numerator = flex_rows + flex_draw
    denominator = len(completed) + flex_draw
    if denominator == 0:
        ratio = Fraction(0, 1)
    else:
        ratio = Fraction(numerator, denominator)
    premium = flex_premium_pct(ratio)
    return qi(Fraction(base_cents) * (1 + premium))


# ---- calculation: cost_per_package --------------------------------------


def calc_provisional_cost_per_package(plan):
    numerator = plan["planned_labor_cents"] + FIXED_OVERHEAD_CENTS_PER_SHIFT
    denominator = plan["forecast_volume"]
    if denominator <= 0:
        denominator = 1
    return q(Fraction(numerator, denominator), 2)


def calc_final_cost_per_package(plan):
    rework = plan["missort_package_count"] * REWORK_CENTS_PER_MISSORT_PACKAGE
    numerator = plan["actual_labor_cents"] + FIXED_OVERHEAD_CENTS_PER_SHIFT + rework
    denominator = plan["sorted_package_count"] - plan["missort_package_count"]
    if denominator < 1:
        denominator = 1
    return q(Fraction(numerator, denominator), 2)


# ---- calculation: staffing_commitment_and_gap ---------------------------


def recompute_plan_staffing(plan):
    no_shows = len([a for a in assignments_of_plan(plan["id"]) if a["status"] == "NO_SHOW"])
    committed = (
        plan["planned_core_headcount"]
        + plan["planned_seasonal_headcount"]
        + plan["flex_draw_count"]
        - no_shows
    )
    gap = plan["required_headcount"] - committed
    if gap < 0:
        gap = 0
    changed = plan["committed_headcount"] != committed or plan["staffing_gap"] != gap
    plan["committed_headcount"] = committed
    plan["staffing_gap"] = gap
    return changed


# ---- calculation: attrition_risk_score ----------------------------------


def tenure_bucket_base(tenure_days):
    if tenure_days <= 14:
        return TENURE_BUCKET_RISK["D0_14"]
    if tenure_days <= 45:
        return TENURE_BUCKET_RISK["D15_45"]
    if tenure_days <= 120:
        return TENURE_BUCKET_RISK["D46_120"]
    return TENURE_BUCKET_RISK["D121_PLUS"]


def recompute_attrition(worker):
    tenure_days = (clock_date() - worker["_hire_date"]).days
    worker["tenure_days"] = tenure_days
    bucket_base = tenure_bucket_base(tenure_days)
    class_adj = HIRE_CLASS_ATTRITION_ADJ[worker["hire_class"]]
    observed_adj = (
        NO_SHOW_WEIGHT * worker["no_show_count"]
        + MISSED_TRAINING_WEIGHT * worker["training_sessions_missed"]
    )
    if worker["status"] == "CERTIFIED":
        observed_adj = observed_adj - CERTIFIED_CREDIT
    if worker["completed_assignment_count"] < MIN_OBSERVATION_ASSIGNMENTS:
        basis = "COHORT_BASELINE"
        raw = bucket_base + class_adj
        if raw > SCORE_CEILING:
            raw = SCORE_CEILING
        score = q(raw, 4)
    else:
        basis = "INDIVIDUAL_OBSERVED"
        raw = bucket_base + class_adj + observed_adj
        if raw < SCORE_FLOOR:
            raw = SCORE_FLOOR
        if raw > SCORE_CEILING:
            raw = SCORE_CEILING
        score = q(raw, 4)
    worker["attrition_risk_basis"] = basis
    worker["attrition_risk_score"] = score
    worker["attrition_flagged"] = score >= ATTRITION_FLAG_THRESHOLD


# ---- calculation: cube_consumption --------------------------------------


def calc_cube(load, counts):
    batch = Decimal("0")
    for size_class in ("SMALL", "MEDIUM", "LARGE", "OVERSIZED"):
        line = q(Fraction(counts[size_class]) * Fraction(CUFT_PER_PACKAGE[size_class]), 2)
        batch += line
    new_cube = q(Fraction(load["cube_used_cuft"]) + Fraction(batch), 2)
    return new_cube


def cube_utilization(cube_used, trailer_cube):
    if trailer_cube <= 0:
        return Decimal("0.00")
    return q(Fraction(cube_used) / Fraction(trailer_cube) * 100, 2)


# ---- selector: attributed_shift_plan ------------------------------------


def attributed_shift_plan(center_id):
    now = clock_dt()
    eligible = [
        p
        for p in plans_of(center_id)
        if p["status"] in ("APPROVED", "AT_RISK")
        and p["_shift_window_start"] <= now < p["_shift_window_end"]
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda p: (p["_shift_window_start"], p["_seq"]))
    return eligible[0]


# ---- selector: reroute_chute_selection ----------------------------------


def reroute_chute_selection(lane_id):
    now = clock_dt()
    eligible = []
    for assignment in chute_assignments_of_lane(lane_id):
        if assignment["status"] != "ACTIVE":
            continue
        if not (assignment["_window_start"] <= now < assignment["_window_end"]):
            continue
        chute = db.sort_chutes.get(assignment["chute_id"])
        if chute is None or chute["status"] != "ACTIVE":
            continue
        eligible.append((assignment, chute))
    if not eligible:
        return None
    eligible.sort(key=lambda pair: (-pair[1]["throughput_pph"], pair[0]["_seq"]))
    return eligible[0][1]


# ---- cascade: no-show (PRD §3.7 links 1..6) -----------------------------


def run_no_show_cascade(assignment):
    """L1..L6 of the no-show cascade. `assignment` is already ASSIGNED."""
    # L1
    assignment["status"] = "NO_SHOW"
    touch(assignment)
    worker = db.workers.get(assignment["worker_id"])
    if worker is not None:
        worker["no_show_count"] = worker["no_show_count"] + 1
        # L2
        recompute_attrition(worker)
        touch(worker)

    plan = db.shift_plans.get(assignment["shift_plan_id"])
    if plan is None:
        return
    # L3
    if recompute_plan_staffing(plan):
        touch(plan)
    center = db.sort_centers.get(plan["sort_center_id"])
    # L4
    if plan["status"] == "APPROVED" and plan["staffing_gap"] > AT_RISK_GAP_THRESHOLD:
        plan["status"] = "AT_RISK"
        touch(plan)
        # L5
        draw = min(plan["staffing_gap"], center["flex_pool_available"]) if center else 0
        if draw < 0:
            draw = 0
        if center is not None:
            center["flex_pool_available"] = center["flex_pool_available"] - draw
            center["flex_pool_reserved"] = center["flex_pool_reserved"] + draw
            touch(center)
        plan["flex_draw_count"] = plan["flex_draw_count"] + draw
        recompute_plan_staffing(plan)
        plan["unfilled_gap"] = plan["staffing_gap"]
        touch(plan)
        # L6
        if plan["staffing_gap"] == 0:
            plan["status"] = "APPROVED"
            plan["unfilled_gap"] = 0
            touch(plan)


# ---- cascade: shift-plan close (chute assignments -> ENDED) -------------


def end_chute_assignments_for_close(plan):
    center_id = plan["sort_center_id"]
    shift_end = plan["_shift_window_end"]
    affected_lanes = set()
    for assignment in db.chute_assignments.values():
        if assignment["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        chute = db.sort_chutes.get(assignment["chute_id"])
        if chute is None or chute["sort_center_id"] != center_id:
            continue
        if assignment["_window_end"] > shift_end:
            continue
        assignment["status"] = "ENDED"
        assignment["effective_window_end"] = assignment["window_end"]
        touch(assignment)
        affected_lanes.add(assignment["destination_lane_id"])
    for lane_id in affected_lanes:
        lane = db.destination_lanes.get(lane_id)
        if lane is not None:
            recompute_lane_and_touch(lane)
