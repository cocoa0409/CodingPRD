"""Calculation engine (PRD 2.5, 2.12, 3.2, 3.4, 3.5, 3.6, 3.7, 3.9)."""
from db import db
from util import r2, r3, r4

# --- spc_violation_classification
WARN_SIGMA_MULT = 2.0
RUN_SIGMA_MULT = 1.0
WE_RUN_LENGTH = 4

# --- excursion_severity_score
DEVIATION_WEIGHT = 60.0
LOT_WEIGHT = 3.0
LOT_CAP = 10
OOS_PENALTY = 10.0
MAX_YIELD_LOSS = 0.25
MEDIUM_BAND = 40.0
HIGH_BAND = 70.0
PARTICLE_TOOL_DOWN_MULT = 2.0

# --- chamber_dispatch_score
QUAL_DECAY_WEIGHT = 40.0
PARTICLE_WEIGHT = 25.0
PM_WEIGHT = 20.0

# --- die_yield_and_speed_grade_allocation
DOMINANCE_THRESHOLD = 0.45
SIGNATURE_PRECEDENCE = ("SCRATCH_LINE", "EDGE_RING", "CENTER_CLUSTER", "PARAMETRIC_SHIFT")
SORT_EXCURSION_THRESHOLD = 0.10

# --- lot_cycle_time_days
QUEUE_FACTOR = {"STANDARD": 1.60, "HOT": 1.25, "SUPER_HOT": 1.05}

# --- wafer_start_capacity_commitment
TIER_1_MIN = 0.50
TIER_2_MIN = 0.70
TIER_3_MIN = 0.90
SURCHARGE_RATE = {"TIER_0": 0.00, "TIER_1": 0.05, "TIER_2": 0.12, "TIER_3": 0.25}

# --- recipe_change_risk_score
CLASS_WEIGHT = {"MINOR": 10.0, "MAJOR": 35.0, "CRITICAL": 60.0}
DELTA_WEIGHT = 25.0
DELTA_NORM = 0.10
IMPACT_WEIGHT = 15.0
IMPACT_NORM = 20.0
REQUAL_THRESHOLD = 70.0
MAX_REVISION_ROUNDS = 2

# --- ledgers
INITIAL_CAPACITY_HOURS = 720.0
MAX_REWORK_COUNT = 2

SIGNATURE_FIELD = {
    "EDGE_RING": "edge_ring_fails",
    "CENTER_CLUSTER": "center_cluster_fails",
    "SCRATCH_LINE": "scratch_line_fails",
    "PARAMETRIC_SHIFT": "parametric_shift_fails",
}


# ------------------------------------------------------------------ SPC engine

def classify_measurement(chart, measured_value):
    """calculations.spc_violation_classification.

    Returns (classification, deviation_sigma, run_rule_triggered, side).
    Mutates nothing; the caller applies the chart updates.
    """
    delta = measured_value - chart["target"]
    deviation_sigma = r4(abs(delta) / chart["sigma"])

    # spec limits are STRICT, control limits are INCLUSIVE (asymmetric on purpose)
    if measured_value > chart["usl"] or measured_value < chart["lsl"]:
        classification = "OUT_OF_SPEC"
    elif measured_value >= chart["ucl"] or measured_value <= chart["lcl"]:
        classification = "OUT_OF_CONTROL"
    elif abs(delta) >= WARN_SIGMA_MULT * chart["sigma"]:
        classification = "WARN"
    else:
        classification = "IN_CONTROL"

    side = "ABOVE" if delta > 0 else ("BELOW" if delta < 0 else "NONE")

    if abs(delta) >= RUN_SIGMA_MULT * chart["sigma"] and side == chart["last_side"]:
        count = chart["consecutive_same_side_count"] + 1
    elif abs(delta) >= RUN_SIGMA_MULT * chart["sigma"]:
        count = 1
    else:
        count = 0
    run_rule_triggered = count >= WE_RUN_LENGTH
    return classification, deviation_sigma, run_rule_triggered, side, count


# ------------------------------------------------------------- excursion score

def affected_lot_ids(excursion, variant):
    """The distinct lot set behind affected_lot_count (PRD 3.7)."""
    source = excursion["source_type"]
    if source == "SPC":
        chart = db.spc_charts.get(excursion["spc_chart_id"])
        if chart is None:
            return set()
        if variant == "PROVISIONAL":
            statuses = ("OPEN",)
            flow_states = ("RELEASED", "IN_PROCESS")
        else:
            statuses = ("OPEN", "COMPLETED")
            flow_states = ("RELEASED", "IN_PROCESS", "AT_SORT", "COMPLETED")
        return {
            run["lot_id"]
            for run in db.step_runs.values()
            if run["step_id"] == chart["step_id"]
            and run["status"] in statuses
            and run["lot_id"] in db.lots
            and db.lots[run["lot_id"]]["flow_state"] in flow_states
        }
    if source == "PARTICLE":
        if variant == "PROVISIONAL":
            statuses = ("OPEN",)
            flow_states = ("RELEASED", "IN_PROCESS")
        else:
            statuses = ("OPEN", "COMPLETED", "ABORTED")
            flow_states = ("RELEASED", "IN_PROCESS", "AT_SORT", "COMPLETED")
        return {
            run["lot_id"]
            for run in db.step_runs.values()
            if run["chamber_id"] == excursion["chamber_id"]
            and run["status"] in statuses
            and run["lot_id"] in db.lots
            and db.lots[run["lot_id"]]["flow_state"] in flow_states
        }
    # DIE_SORT
    if variant == "PROVISIONAL":
        return {excursion["lot_id"]} if excursion["lot_id"] else set()
    lot = db.lots.get(excursion["lot_id"])
    if lot is None:
        return set()
    flow_states = ("RELEASED", "IN_PROCESS", "AT_SORT", "COMPLETED")
    return {
        other["id"]
        for other in db.lots.values()
        if other["flow_id"] == lot["flow_id"] and other["flow_state"] in flow_states
    }


def severity(excursion, variant):
    """calculations.excursion_severity_score -> (score, band, affected_lot_count)."""
    affected = affected_lot_ids(excursion, variant)
    count = len(affected)
    trigger = excursion["trigger_value"]
    source = excursion["source_type"]
    if source == "SPC":
        chart = db.spc_charts[excursion["spc_chart_id"]]
        ratio = abs(trigger - chart["target"]) / (chart["usl"] - chart["target"])
    elif source == "DIE_SORT":
        ratio = trigger / MAX_YIELD_LOSS
    else:
        chamber = db.chambers[excursion["chamber_id"]]
        ratio = trigger / chamber["particle_limit"]

    base = DEVIATION_WEIGHT * min(1.0, ratio)
    spread = LOT_WEIGHT * min(LOT_CAP, count)
    spec = OOS_PENALTY if excursion.get("_opening_out_of_spec") else 0.0
    score = r2(base + spread + spec)
    band = "HIGH" if score >= HIGH_BAND else ("MEDIUM" if score >= MEDIUM_BAND else "LOW")
    return score, band, count


# ------------------------------------------------------------- dispatch score

def dispatch_score(chamber, equipment, lot, now):
    """calculations.chamber_dispatch_score ranking expression."""
    expires = chamber["qual_expires_at"]
    qualified_at = chamber["qualified_at"]
    window = (expires - qualified_at).total_seconds()
    if window <= 0:
        qual_remaining_ratio = 0.0
    else:
        qual_remaining_ratio = max(0.0, (expires - now).total_seconds() / window)
    if lot["priority_class"] == "SUPER_HOT":
        pm_term = 0.0
    else:
        pm_term = PM_WEIGHT * min(1.0, equipment["hours_since_pm"] / equipment["pm_interval_hours"])
    return r2(
        100.0
        - QUAL_DECAY_WEIGHT * (1.0 - qual_remaining_ratio)
        - PARTICLE_WEIGHT * min(1.0, chamber["particle_count"] / chamber["particle_limit"])
        - pm_term
    )


# ------------------------------------------------------------------- die sort

def sort_yield_stage(baseline_yield, wafer_results):
    ordered = sorted(wafer_results, key=lambda w: w["wafer_slot"])
    per_wafer = [r4(w["good_die"] / w["tested_die"]) for w in ordered]
    sort_yield = r4(sum(per_wafer) / len(per_wafer))
    good_die_total = sum(w["good_die"] for w in ordered)
    yield_loss_ratio = r4(max(0.0, (baseline_yield - sort_yield) / baseline_yield))
    return sort_yield, good_die_total, yield_loss_ratio


def dominant_signature(wafer_results):
    totals = {}
    for mode, field in SIGNATURE_FIELD.items():
        totals[mode] = sum(w[field] for w in wafer_results)
    total_fails = sum(totals.values())
    if total_fails == 0:
        return "NONE"
    shares = {mode: r4(totals[mode] / total_fails) for mode in totals}
    top = max(shares.values())
    if top < DOMINANCE_THRESHOLD:
        return "NONE"
    for mode in SIGNATURE_PRECEDENCE:
        if shares[mode] == top:
            return mode
    return "NONE"


def speed_grade_waterfall(good_die_total, premium_target_die, standard_target_die):
    premium = min(premium_target_die, good_die_total)
    standard = min(standard_target_die, good_die_total - premium)
    value = good_die_total - premium - standard
    return premium, standard, value


# ------------------------------------------------------------------ cycle time

def remaining_standard_hours(lot):
    total = sum(
        step["standard_hours"]
        for step in db.process_steps.values()
        if step["flow_id"] == lot["flow_id"] and step["step_seq"] > lot["current_step_seq"]
    )
    return r2(total)


def cycle_time_projection(lot, now, target_days):
    remaining = remaining_standard_hours(lot)
    queue_factor = QUEUE_FACTOR[lot["priority_class"]]
    projected_remaining_days = r3(remaining * queue_factor / 24.0)
    elapsed_days = r3((now - lot["released_at"]).total_seconds() / 86400.0)
    projected = r3(elapsed_days + projected_remaining_days)
    status = "AT_RISK" if projected > target_days else "ON_TARGET"
    return {
        "remaining_standard_hours": remaining,
        "queue_factor": queue_factor,
        "projected_remaining_days": projected_remaining_days,
        "elapsed_days": elapsed_days,
        "projected_cycle_time_days": projected,
        "cycle_time_status": status,
    }


def chronological_cycle_time(lot):
    return r3((lot["completed_at"] - lot["released_at"]).total_seconds() / 86400.0)


# ------------------------------------------------------- capacity commitment

def capacity_commitment(planned_wafer_starts, total_standard_hours, capacity_budget_hours):
    base_hours = r2(planned_wafer_starts * total_standard_hours)
    pre_utilization = r4(base_hours / capacity_budget_hours)
    if pre_utilization >= TIER_3_MIN:
        tier = "TIER_3"
    elif pre_utilization >= TIER_2_MIN:
        tier = "TIER_2"
    elif pre_utilization >= TIER_1_MIN:
        tier = "TIER_1"
    else:
        tier = "TIER_0"
    surcharge_hours = r2(base_hours * SURCHARGE_RATE[tier])
    committed_hours = r2(base_hours + surcharge_hours)
    return base_hours, pre_utilization, tier, surcharge_hours, committed_hours


# ------------------------------------------------------------ ECN risk score

def impact_lot_count(recipe_id):
    steps_by_flow = {}
    for step in db.process_steps.values():
        if step["recipe_id"] == recipe_id:
            steps_by_flow.setdefault(step["flow_id"], []).append(step)
    count = 0
    for lot in db.lots.values():
        if lot["flow_state"] not in ("RELEASED", "IN_PROCESS"):
            continue
        for step in steps_by_flow.get(lot["flow_id"], ()):
            if step["step_seq"] > lot["current_step_seq"]:
                count += 1
                break
    return count


def recipe_change_risk(recipe, change_class, proposed_target):
    impact = impact_lot_count(recipe["id"])
    relative_delta = abs(proposed_target - recipe["target_value"]) / recipe["target_value"]
    score = r2(
        CLASS_WEIGHT[change_class]
        + DELTA_WEIGHT * min(1.0, relative_delta / DELTA_NORM)
        + IMPACT_WEIGHT * min(1.0, impact / IMPACT_NORM)
    )
    return impact, score, score >= REQUAL_THRESHOLD
