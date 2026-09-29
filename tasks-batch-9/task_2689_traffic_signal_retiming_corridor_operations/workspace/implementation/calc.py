"""Every calculation in PRD section 3 / SCAFFOLD section 1.3.

All rounding goes through round_half_up, which is implemented with decimal so
that a value exactly halfway between two representable results always moves to
the larger magnitude (Python's built-in round() is banker's rounding and would
give the wrong answer).
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# ---- constants -------------------------------------------------------------
NEVER_RETIMED_AGE_DAYS = 3650
COMPLAINT_WINDOW_DAYS = 365

AGE_SATURATION_DAYS = 1825
VOLUME_SATURATION_PCT = 25.0
COMPLAINT_SATURATION_COUNT = 20
WEIGHT_AGE = 0.45
WEIGHT_VOLUME = 0.35
WEIGHT_COMPLAINT = 0.20
CLASS_MULTIPLIER = {"ARTERIAL": 1.25, "COLLECTOR": 1.00, "LOCAL": 0.80}
SELECT_SCORE_THRESHOLD = 50.00
DEFER_SCORE_THRESHOLD = 35.00

SATURATION_FLOW_VPHPL = 1800
LOST_TIME_PER_PHASE_SEC = 4.0
OVERSATURATION_RATIO = 0.95
CYCLE_ROUNDING_MULTIPLE_SEC = 5
MIN_CYCLE_SEC = 60

PROGRESSION_SPEED_FPS = 44.0

WALKING_SPEED_STD_FPS = 3.5
WALKING_SPEED_EXTENDED_FPS = 3.0
MIN_WALK_STD_SEC = 4.0
MIN_WALK_APS_SEC = 7.0

MAX_PRIORITY_FRACTION = 0.20
MAX_TUNING_ROUNDS = 3

PERIOD_PREFERENCE = {"PM_PEAK": 3, "AM_PEAK": 2, "MID_DAY": 1}


def round_half_up(value, places=0):
    """Round half away from zero to `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    result = Decimal(repr(float(value))).quantize(quant, rounding=ROUND_HALF_UP)
    if places <= 0:
        return int(result)
    return float(result)


def ceil_to_tenth(value):
    """Raise up to the next tenth of a second."""
    scaled = Decimal(repr(float(value))) * 10
    return float(int(math.ceil(float(scaled) - 1e-9))) / 10.0


def ceil_to_multiple(value, multiple):
    return int(math.ceil((float(value) - 1e-9) / multiple)) * multiple


# ---- intersection ----------------------------------------------------------

def operational_posture(comm_status, detection_status):
    if comm_status == "OFFLINE" or detection_status == "FAILED":
        return "BLOCKED"
    if comm_status == "INTERMITTENT" or detection_status in ("PARTIAL", "NONE"):
        return "RESTRICTED"
    return "READY"


def timing_plan_age_days(last_retimed_at, now):
    if last_retimed_at is None:
        return NEVER_RETIMED_AGE_DAYS
    elapsed = int((now - last_retimed_at).total_seconds())
    if elapsed < 0:
        elapsed = 0
    return elapsed // 86400


# ---- corridor scoring ------------------------------------------------------

def avg_plan_age_days(ages):
    """Mean of the supplied per-member ages, 2dp, applied once."""
    if not ages:
        return 0.00
    return round_half_up(sum(ages) / float(len(ages)), 2)


def priority_score(avg_age, annual_volume_change_pct, complaint_count_12mo, jurisdiction_class):
    plan_age_component = min(1.0, float(avg_age) / AGE_SATURATION_DAYS)
    volume_component = min(1.0, abs(float(annual_volume_change_pct)) / VOLUME_SATURATION_PCT)
    complaint_component = min(1.0, float(complaint_count_12mo) / COMPLAINT_SATURATION_COUNT)
    multiplier = CLASS_MULTIPLIER[jurisdiction_class]
    raw = (
        WEIGHT_AGE * plan_age_component
        + WEIGHT_VOLUME * volume_component
        + WEIGHT_COMPLAINT * complaint_component
    ) * multiplier
    return round_half_up(min(1.0, raw) * 100.0, 2)


# ---- Webster recommended cycle --------------------------------------------

def critical_flow_ratio(phase_volumes):
    """Exact (unrounded) critical flow ratio sum."""
    return sum(phase_volumes.values()) / float(SATURATION_FLOW_VPHPL)


def is_oversaturated(cfr_exact):
    return cfr_exact >= OVERSATURATION_RATIO


def recommended_cycle_sec(phase_volumes, max_cycle_length_sec, cfr_exact=None):
    if cfr_exact is None:
        cfr_exact = critical_flow_ratio(phase_volumes)
    phase_count = len(phase_volumes)
    lost_time = phase_count * LOST_TIME_PER_PHASE_SEC
    webster = (1.5 * lost_time + 5.0) / (1.0 - cfr_exact)
    rounded_up = ceil_to_multiple(webster, CYCLE_ROUNDING_MULTIPLE_SEC)
    clamped = min(rounded_up, max_cycle_length_sec)
    return max(MIN_CYCLE_SEC, clamped)


def pick_pipeline_count(counts):
    """Greatest count_date, then greatest created_at, then PM_PEAK > AM_PEAK > MID_DAY."""
    if not counts:
        return None
    return sorted(
        counts,
        key=lambda c: (
            c["count_date"],
            c["created_at"],
            PERIOD_PREFERENCE.get(c["period"], 0),
            c["_seq"],
        ),
    )[-1]


# ---- coordination ----------------------------------------------------------

def coordinated_cycle(recommended_cycles):
    peak = max(recommended_cycles)
    return ceil_to_multiple(peak, CYCLE_ROUNDING_MULTIPLE_SEC)


def rescale_splits(phases, target_cycle):
    """phases: PhaseSplit rows in phase_number ASC order.  Mutates effective_split_sec."""
    drafted_total = sum(p["split_sec"] for p in phases)
    if drafted_total <= 0:
        return 0, 0
    for phase in phases:
        phase["effective_split_sec"] = round_half_up(
            phase["split_sec"] * float(target_cycle) / float(drafted_total), 0
        )
    residual = target_cycle - sum(p["effective_split_sec"] for p in phases)
    coordinated = sorted(phases, key=lambda p: (-p["min_green_sec"], p["phase_number"]))[0]
    coordinated["effective_split_sec"] = coordinated["effective_split_sec"] + residual
    effective_total = sum(p["effective_split_sec"] for p in phases)
    return drafted_total, effective_total


def offset_sec(cumulative_ft, cycle_length_sec):
    cumulative_travel_sec = float(cumulative_ft) / PROGRESSION_SPEED_FPS
    whole = round_half_up(cumulative_travel_sec, 0)
    if cycle_length_sec <= 0:
        return 0
    return whole % cycle_length_sec


# ---- pedestrian compliance ------------------------------------------------

def walking_speed_fps(walking_speed_standard):
    if walking_speed_standard == "STD_3_5_FPS":
        return WALKING_SPEED_STD_FPS
    return WALKING_SPEED_EXTENDED_FPS


def ped_requirements(split, intersection):
    speed = walking_speed_fps(intersection["walking_speed_standard"])
    required_ped_clear = ceil_to_tenth(float(split["crosswalk_length_ft"]) / speed)
    required_walk = MIN_WALK_APS_SEC if intersection["aps_installed"] else MIN_WALK_STD_SEC
    required_phase_length = (
        required_walk
        + required_ped_clear
        + float(split["yellow_sec"])
        + float(split["red_clearance_sec"])
    )
    provided_ped_clear = float(split["ped_clear_sec"])
    provided_walk = float(split["walk_sec"])
    provided_phase_length = float(split["effective_split_sec"])
    if provided_ped_clear < required_ped_clear:
        result, reason = "FAIL", "PED_CLEAR_SHORT"
    elif provided_walk < required_walk:
        result, reason = "FAIL", "WALK_SHORT"
    elif provided_phase_length < required_phase_length:
        result, reason = "FAIL", "PHASE_TOO_SHORT"
    else:
        result, reason = "PASS", None
    return {
        "walking_speed_fps": speed,
        "required_ped_clear_sec": required_ped_clear,
        "provided_ped_clear_sec": provided_ped_clear,
        "required_walk_sec": required_walk,
        "provided_walk_sec": provided_walk,
        "required_phase_length_sec": required_phase_length,
        "provided_phase_length_sec": provided_phase_length,
        "result": result,
        "failure_reason": reason,
    }


# ---- priority budget waterfall -------------------------------------------

def priority_budget_sec(deployed_coordinated_cycle_sec):
    if deployed_coordinated_cycle_sec is None:
        return 0
    return int(math.floor(deployed_coordinated_cycle_sec * MAX_PRIORITY_FRACTION))


def priority_order(configs):
    """EVP before TSP, then conflict_resolution_rank ASC, then created_at ASC."""
    return sorted(
        configs,
        key=lambda c: (
            0 if c["priority_type"] == "EVP" else 1,
            c["conflict_resolution_rank"],
            c["created_at"],
            c["_seq"],
        ),
    )


def allocate_priority(budget, deployed_configs):
    """Returns {config_id: granted_extension_sec} for the deployed pool."""
    remaining = budget
    grants = {}
    for cfg in priority_order(deployed_configs):
        granted = min(cfg["requested_max_extension_sec"], remaining)
        if granted < 0:
            granted = 0
        grants[cfg["id"]] = granted
        remaining -= granted
    return grants


# ---- performance metrics --------------------------------------------------

def unweighted_mean(runs):
    total = sum(float(r["duration_sec"]) for r in runs)
    return round_half_up(total / float(len(runs)), 2)


def weighted_mean(runs):
    numerator = sum(float(r["duration_sec"]) * r["total_arrivals"] for r in runs)
    denominator = sum(r["total_arrivals"] for r in runs)
    if denominator == 0:
        return 0.00
    return round_half_up(numerator / float(denominator), 2)


def performance_metrics(before_runs, after_runs, weighted):
    mean_before = weighted_mean(before_runs) if weighted else unweighted_mean(before_runs)
    mean_after = weighted_mean(after_runs) if weighted else unweighted_mean(after_runs)
    if mean_before == 0:
        delay_reduction = 0.00
    else:
        delay_reduction = round_half_up(100.0 * (mean_before - mean_after) / mean_before, 2)
    stops_before = sum(r["stops_count"] for r in before_runs)
    stops_after = sum(r["stops_count"] for r in after_runs)
    if stops_before == 0:
        stops_reduction = 0.00
    else:
        stops_reduction = round_half_up(
            100.0 * (stops_before - stops_after) / float(stops_before), 2
        )
    aog_before = _aog(before_runs)
    aog_after = _aog(after_runs)
    return {
        "mean_travel_time_before_sec": mean_before,
        "mean_travel_time_after_sec": mean_after,
        "delay_reduction_pct": delay_reduction,
        "total_stops_before": stops_before,
        "total_stops_after": stops_after,
        "stops_reduction_pct": stops_reduction,
        "aog_pct_before": aog_before,
        "aog_pct_after": aog_after,
        "included_after_run_count": len(after_runs),
    }


def _aog(runs):
    total_arrivals = sum(r["total_arrivals"] for r in runs)
    if total_arrivals == 0:
        return 0.00
    on_green = sum(r["arrivals_on_green_count"] for r in runs)
    return round_half_up(100.0 * on_green / float(total_arrivals), 2)
