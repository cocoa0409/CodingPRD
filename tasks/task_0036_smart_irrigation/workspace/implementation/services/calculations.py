"""Calculation rules per scaffold §1.3 / PRD §3.

Implements:
  - crop_water_demand: planned_volume_liters from crop_stage / area / moisture / rainfall
  - quota_consumption_provisional_vs_final: aggregate provisional vs final usage
  - alert_severity_score: provisional & reconciled severity variants
  - tiered_water_fee: peak/off-peak tiered pricing with PER-LINE rounding
  - bill_total_settlement: subtotal minus rounded carry-forward credit
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB
from services.common import (
    round_half_up_1,
    round_half_up_2,
    round_half_up_int,
    to_aware_utc,
)


# ----- crop_water_demand constants ---------------------------------------------------------------

STAGE_BASE_LITERS_PER_HECTARE = {
    "SEEDLING": 20000,
    "VEGETATIVE": 35000,
    "FLOWERING": 50000,
    "FRUITING": 45000,
    "MATURE": 25000,
}

TARGET_MOISTURE_PCT = {
    "WHEAT": 60,
    "CORN": 65,
    "RICE": 80,
    "COTTON": 55,
    "VEGETABLE": 70,
}

RAINFALL_OFFSET_MM = 30


# ----- alert_severity_score constants ------------------------------------------------------------

W_RULE = {
    "SENSOR_OFFLINE": 2,
    "ABNORMAL_FLOW": 3,
    "PIPE_BURST_SUSPICION": 5,
    "VALVE_FAULT": 4,
}

W_SUBJECT = {
    "SENSOR": 1,
    "PLOT": 2,
    "VALVE_GROUP": 3,
}

W_RECENT_ABNORMAL = 0.5


# ----- tiered_water_fee constants ----------------------------------------------------------------

PEAK_HOURS = {6, 7, 8, 9, 18, 19, 20, 21}

PEAK_TIERS = [
    {"upper_bound_liters": 100000, "rate_cents_per_liter": 30},
    {"upper_bound_liters": 250000, "rate_cents_per_liter": 50},
    {"upper_bound_liters": 999999999, "rate_cents_per_liter": 80},
]

OFFPEAK_TIERS = [
    {"upper_bound_liters": 100000, "rate_cents_per_liter": 18},
    {"upper_bound_liters": 250000, "rate_cents_per_liter": 30},
    {"upper_bound_liters": 999999999, "rate_cents_per_liter": 50},
]

TENANT_MULTIPLIER = {
    "ACTIVE": Decimal("1.0"),
    "SUSPENDED": Decimal("1.25"),
}

BLENDED_RATE_CENTS_PER_LITER = 25


EPSILON = 1e-6


# ----- crop_water_demand --------------------------------------------------------------------------

def latest_valid_moisture_pct(plot_id):
    """Most recent VALID SensorReading from a SOIL_MOISTURE sensor on the plot.

    Ordered by reading_timestamp DESC; if none, default to 50.
    """
    candidates = []
    for sensor in DB.sensors.values():
        if sensor.get("plot_id") != plot_id:
            continue
        if sensor.get("sensor_type") != "SOIL_MOISTURE":
            continue
        for rid in DB.readings_by_sensor.get(sensor["id"], []):
            r = DB.sensor_readings.get(rid)
            if not r:
                continue
            if r.get("validity") != "VALID":
                continue
            candidates.append(r)
    if not candidates:
        return 50.0
    candidates.sort(key=lambda r: r.get("reading_timestamp"), reverse=True)
    return float(candidates[0].get("value", 50.0))


def latest_rainfall_mm(plot_id, now):
    """Most recent VALID SensorReading from a WEATHER_STATION sensor on the plot
    within the last 24 hours; defaults to 0 if none. Falls back to a cached
    value emitted via /_events/emit WEATHER_RAINFALL when no sensor reading
    is available.
    """
    candidates = []
    cutoff = to_aware_utc(now) - timedelta(hours=24)
    for sensor in DB.sensors.values():
        if sensor.get("plot_id") != plot_id:
            continue
        if sensor.get("sensor_type") != "WEATHER_STATION":
            continue
        for rid in DB.readings_by_sensor.get(sensor["id"], []):
            r = DB.sensor_readings.get(rid)
            if not r:
                continue
            if r.get("validity") != "VALID":
                continue
            ts = to_aware_utc(r.get("reading_timestamp"))
            if ts is None or ts < cutoff:
                continue
            candidates.append(r)
    if not candidates:
        # Fall back to cached rainfall (set by /_events/emit WEATHER_RAINFALL).
        if plot_id in DB.cached_rainfall_mm:
            return float(DB.cached_rainfall_mm[plot_id])
        return 0.0
    candidates.sort(key=lambda r: r.get("reading_timestamp"), reverse=True)
    return float(candidates[0].get("value", 0.0))


def compute_crop_water_demand(plot, now):
    """Return planned_volume_liters for an AUTO plan on this plot."""
    crop_stage = plot["crop_stage"]
    crop_type = plot["crop_type"]
    area = float(plot["area_hectares"])

    base = STAGE_BASE_LITERS_PER_HECTARE[crop_stage] * area
    moisture_pct = latest_valid_moisture_pct(plot["id"])
    rainfall_mm = latest_rainfall_mm(plot["id"], now)

    moisture_adj = max(0.0, (TARGET_MOISTURE_PCT[crop_type] - moisture_pct) / 100.0)
    weather_adj = max(0.0, (1.0 - rainfall_mm / RAINFALL_OFFSET_MM))

    planned = base * (1.0 + moisture_adj) * weather_adj
    return round_half_up_2(planned)


# ----- quota_consumption_provisional_vs_final -----------------------------------------------------

def _plan_ids_for_plot(plot_id):
    return {p["id"] for p in DB.irrigation_plans.values() if p.get("plot_id") == plot_id}


def compute_provisional_used_liters(quota):
    """Sum requested_volume_liters across in-flight ControlCommands belonging to plans on this plot
    whose created_at falls inside [period_start, period_end). OFFLINE_LOCAL counts as provisional.
    """
    plot_id = quota["plot_id"]
    period_start = to_aware_utc(quota["period_start"])
    period_end = to_aware_utc(quota["period_end"])
    plan_ids = _plan_ids_for_plot(plot_id)

    total = Decimal("0")
    for cmd in DB.control_commands.values():
        if cmd["plan_id"] not in plan_ids:
            continue
        if cmd["status"] not in ("PENDING", "DISPATCHING", "EXECUTING", "OFFLINE_LOCAL"):
            continue
        ts = to_aware_utc(cmd.get("created_at"))
        if ts is None or ts < period_start or ts >= period_end:
            continue
        total += Decimal(str(cmd.get("requested_volume_liters", 0)))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_final_used_liters(quota):
    """Sum actual_volume_liters across EXECUTED ControlCommands whose feedback_received_at falls
    inside [period_start, period_end).
    """
    plot_id = quota["plot_id"]
    period_start = to_aware_utc(quota["period_start"])
    period_end = to_aware_utc(quota["period_end"])
    plan_ids = _plan_ids_for_plot(plot_id)

    total = Decimal("0")
    for cmd in DB.control_commands.values():
        if cmd["plan_id"] not in plan_ids:
            continue
        if cmd["status"] != "EXECUTED":
            continue
        ts = to_aware_utc(cmd.get("feedback_received_at"))
        if ts is None or ts < period_start or ts >= period_end:
            continue
        total += Decimal(str(cmd.get("actual_volume_liters", 0)))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def effective_allocation(quota):
    return (
        float(quota.get("allocated_liters", 0))
        + float(quota.get("carry_forward_liters", 0))
        + float(quota.get("approval_extra_liters", 0))
    )


def derive_usage_state(quota):
    eff = effective_allocation(quota)
    final_used = float(quota.get("final_used_liters", 0))
    if eff <= 0:
        return "OVER" if final_used > 0 else "UNDER"
    if final_used >= eff - EPSILON:
        return "OVER"
    threshold = float(quota.get("warning_threshold_pct", 80)) / 100.0
    ratio = final_used / eff
    # PRD §3.5: "if the ratio of final_used_liters to effective_allocation
    # is at least warning_threshold_pct divided by 100, the state is
    # WARNING; otherwise the state is UNDER." Inclusive lower bound at
    # exactly threshold (8000/10000 == 0.80 → WARNING) but strict below
    # (7999.99/10000 ≈ 0.799999 → UNDER). PRD §2.6 names a 1e-6 epsilon
    # for floating-point wobble; we treat the ratio comparison itself as
    # exact since 7999.99/10000 differs from 0.80 by exactly 1e-6 and
    # PRD's stated example flags it as UNDER.
    if ratio >= threshold:
        return "WARNING"
    return "UNDER"


# ----- alert_severity_score ------------------------------------------------------------------------

def _sensor_ids_for_subject(alert):
    """Return the set of sensor IDs whose readings count for this alert's recency contribution.

    - subject_type == SENSOR: just the subject's sensor id (if it exists).
    - subject_type == PLOT: every sensor on that plot.
    - subject_type == VALVE_GROUP: no sensors directly attached, return empty.
    """
    st = alert.get("subject_type")
    sid = alert.get("subject_id")
    if st == "SENSOR":
        return {sid}
    if st == "PLOT":
        return {s["id"] for s in DB.sensors.values() if s.get("plot_id") == sid}
    return set()


def _recent_abnormal_count(alert, now, *, archived_only: bool):
    """Count abnormal readings in the last 24h on the alert's subject sensors.

    archived_only=False => provisional variant (archived flag still false)
    archived_only=True => reconciled variant (archived flag is true)
    """
    sensor_ids = _sensor_ids_for_subject(alert)
    if not sensor_ids:
        return 0
    cutoff = to_aware_utc(now) - timedelta(hours=24)
    count = 0
    for sid in sensor_ids:
        for rid in DB.readings_by_sensor.get(sid, []):
            r = DB.sensor_readings.get(rid)
            if r is None:
                continue
            if r.get("validity") not in ("OUT_OF_RANGE", "ABNORMAL_FILTERED"):
                continue
            ts = to_aware_utc(r.get("reading_timestamp"))
            if ts is None or ts < cutoff:
                continue
            archived = bool(r.get("archived", False))
            if archived_only and not archived:
                continue
            if not archived_only and archived:
                # provisional variant explicitly excludes already-archived
                continue
            count += 1
    return count


def _severity_from_score(score: float) -> str:
    if score >= 6.0 - EPSILON:
        return "CRITICAL"
    if score >= 3.0 - EPSILON:
        return "WARN"
    return "INFO"


def compute_severity(alert, now, *, reconciled: bool):
    rule_w = W_RULE.get(alert.get("rule_code"), 0)
    subj_w = W_SUBJECT.get(alert.get("subject_type"), 0)
    recent = _recent_abnormal_count(alert, now, archived_only=reconciled)
    score = rule_w * 1.0 + subj_w * 1.0 + W_RECENT_ABNORMAL * recent
    score_rounded = round_half_up_1(score)
    return _severity_from_score(score_rounded), score_rounded


# ----- tiered_water_fee --------------------------------------------------------------------------

def _compute_window_lines(window_name, liters, tiers, multiplier):
    """Walk tiers in order; produce per-line items with PER-LINE rounding.

    Returns a list of line items, each a dict with:
      - tier_index (0-based)
      - window: "PEAK" or "OFFPEAK"
      - slab: liters in this tier (float, 2 decimals)
      - rate: rate_cents_per_liter (int)
      - amount_cents: int (rounded half-up)
    """
    items = []
    remaining = Decimal(str(liters))
    prev_bound = Decimal("0")
    if remaining <= 0:
        return items
    for idx, tier in enumerate(tiers):
        upper = Decimal(str(tier["upper_bound_liters"]))
        rate = Decimal(str(tier["rate_cents_per_liter"]))
        slab_cap = upper - prev_bound
        slab = min(remaining, slab_cap)
        if slab <= 0:
            prev_bound = upper
            continue
        line_amount = slab * rate * Decimal(str(multiplier))
        amount_cents = int(line_amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        items.append({
            "tier_index": idx,
            "window": window_name,
            "slab": float(slab.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "rate": int(rate),
            "amount_cents": amount_cents,
        })
        remaining -= slab
        prev_bound = upper
        if remaining <= 0:
            break
    return items


def compute_peak_offpeak_split(plot_id, period_start, period_end):
    """Sum EXECUTED ControlCommand.actual_volume_liters in [period_start, period_end), partitioned
    into peak vs offpeak by hour-of-day of feedback_received_at.
    """
    period_start = to_aware_utc(period_start)
    period_end = to_aware_utc(period_end)
    plan_ids = _plan_ids_for_plot(plot_id)

    peak = Decimal("0")
    offpeak = Decimal("0")
    for cmd in DB.control_commands.values():
        if cmd.get("plan_id") not in plan_ids:
            continue
        if cmd.get("status") != "EXECUTED":
            continue
        ts = to_aware_utc(cmd.get("feedback_received_at"))
        if ts is None or ts < period_start or ts >= period_end:
            continue
        amt = Decimal(str(cmd.get("actual_volume_liters", 0)))
        if ts.hour in PEAK_HOURS:
            peak += amt
        else:
            offpeak += amt
    peak_l = float(peak.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    offpeak_l = float(offpeak.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    return peak_l, offpeak_l


def compute_tiered_fee(peak_liters, offpeak_liters, tenant_status):
    multiplier = TENANT_MULTIPLIER.get(tenant_status, Decimal("1.0"))
    peak_lines = _compute_window_lines("PEAK", peak_liters, PEAK_TIERS, multiplier)
    offpeak_lines = _compute_window_lines("OFFPEAK", offpeak_liters, OFFPEAK_TIERS, multiplier)
    return peak_lines + offpeak_lines


# ----- bill_total_settlement ---------------------------------------------------------------------

def compute_bill_total(line_items, carry_forward_liters):
    raw_subtotal_cents = sum(int(li.get("amount_cents", 0)) for li in line_items)
    credit_cents = round_half_up_int(
        Decimal(str(carry_forward_liters)) * Decimal(str(BLENDED_RATE_CENTS_PER_LITER))
    )
    total = max(0, raw_subtotal_cents - credit_cents)
    return total
