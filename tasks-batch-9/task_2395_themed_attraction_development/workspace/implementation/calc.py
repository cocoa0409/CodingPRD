"""Every derived number in the system.

All arithmetic is exact-decimal (never binary float) per PRD section 2.8, and the
rounding direction of each quantity is fixed and never interchangeable.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

# ------------------------------------------------------------------- constants
MIN_DISPATCH_INTERVAL_SECONDS = 20
SHOW_STOP_PENALTY_EACH = Decimal("0.03")
MAX_SHOW_STOP_PENALTY = Decimal("0.20")
MIN_DERATE_FACTOR = Decimal("0.35")

STANDARD_GUEST_AREA_SQM = Decimal("0.65")
ACCESSIBLE_GUEST_AREA_SQM = Decimal("1.50")
VIRTUAL_RETURN_GUEST_AREA_SQM = Decimal("0.90")

MIN_ACCESSIBLE_SHARE_PCT = Decimal("15")
MAX_VIRTUAL_QUEUE_SHARE_PCT = Decimal("40")

TIER1_BASE_CEILING_CENTS = 500000000
TIER2_BASE_CEILING_CENTS = 2500000000

RESTRICTED_UTILISATION_PCT = Decimal("90")

LIGHTING_WEIGHT = Decimal("0.25")
AUDIO_WEIGHT = Decimal("0.20")
ANIMATION_WEIGHT = Decimal("0.30")
EFFECTS_WEIGHT = Decimal("0.25")
MIN_SHOW_QUALITY_SCORE = Decimal("75.00")

REHEARSAL_PASS_PCT = Decimal("85")

DAYS_PER_YEAR = Decimal("365")

MIN_WIDTH_STANDARD = Decimal("1.10")
MIN_WIDTH_WIDE = Decimal("1.80")

INTERLOCK_BUFFER_MS = 250
BUFFERED_CHANNELS = ("ANIMATION", "SPECIAL_EFFECT")

ZERO_2DP = Decimal("0.00")


# -------------------------------------------------------------------- helpers
def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def half_up_int(value):
    return int(half_up(value, 0))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


# ----------------------------------------- calculations.project_required_hourly_capacity
def required_hourly_capacity(design_day_attendance, peak_hour_share):
    return ceil_int(Decimal(design_day_attendance) * dec(peak_hour_share))


# --------------------------------------------- calculations.ride_system_hourly_capacity
def ride_system_capacity(row):
    vehicles_in_service = min(row["vehicle_count"], row["block_zone_count"] - 1)
    dispatch_interval_seconds = max(
        MIN_DISPATCH_INTERVAL_SECONDS,
        ceil_int(Decimal(row["cycle_time_seconds"]) / Decimal(vehicles_in_service)),
    )
    theoretical = floor_int(Decimal(3600) / Decimal(dispatch_interval_seconds)) * row["riders_per_vehicle"]
    raw_derate = (dec(row["availability_pct"]) / Decimal(100)) * (dec(row["load_efficiency_pct"]) / Decimal(100))
    stop_penalty = min(MAX_SHOW_STOP_PENALTY, dec(row["show_stops_per_hour"]) * SHOW_STOP_PENALTY_EACH)
    derate = max(MIN_DERATE_FACTOR, raw_derate - stop_penalty)
    operational = floor_int(Decimal(theoretical) * derate)
    return dispatch_interval_seconds, theoretical, operational


def apply_ride_system_capacity(row):
    dispatch, theoretical, operational = ride_system_capacity(row)
    row["dispatch_interval_seconds"] = dispatch
    row["theoretical_hourly_capacity_guests"] = theoretical
    row["operational_hourly_capacity_guests"] = operational


# ----------------------------------------------- calculations.queue_segment_capacity
def per_guest_area(routing_type):
    if routing_type == "STANDARD":
        return STANDARD_GUEST_AREA_SQM
    if routing_type == "ACCESSIBLE":
        return ACCESSIBLE_GUEST_AREA_SQM
    return VIRTUAL_RETURN_GUEST_AREA_SQM


def min_width(routing_type):
    if routing_type == "STANDARD":
        return MIN_WIDTH_STANDARD
    return MIN_WIDTH_WIDE


def queue_segment_capacity(length_meters, width_meters, routing_type):
    area = dec(length_meters) * dec(width_meters)
    return floor_int(area / per_guest_area(routing_type))


# ----------------------------------------------- calculations.project_queue_position
def accessible_share_pct(accessible_capacity, total_capacity):
    if total_capacity == 0:
        return ZERO_2DP
    return half_up(Decimal(accessible_capacity) / Decimal(total_capacity) * Decimal(100), 2)


def virtual_queue_allocation(total_capacity, virtual_queue_share_pct):
    return floor_int(Decimal(total_capacity) * dec(virtual_queue_share_pct) / Decimal(100))


def posted_wait_minutes(total_capacity, operational_capacity):
    if not operational_capacity:
        return Decimal("0.0")
    return half_up(Decimal(total_capacity) / Decimal(operational_capacity) * Decimal(60), 1)


# ------------------------------------------- calculations.design_package_cost_of_work
def cost_of_work(base_construction_cost_cents):
    base = base_construction_cost_cents
    if base <= TIER1_BASE_CEILING_CENTS:
        design_fee_pct = Decimal("0.12")
        contingency_pct = Decimal("0.15")
    elif base <= TIER2_BASE_CEILING_CENTS:
        design_fee_pct = Decimal("0.10")
        contingency_pct = Decimal("0.12")
    else:
        design_fee_pct = Decimal("0.085")
        contingency_pct = Decimal("0.10")
    design_fee_cents = half_up_int(Decimal(base) * design_fee_pct)
    contingency_cents = half_up_int(Decimal(base + design_fee_cents) * contingency_pct)
    total = base + design_fee_cents + contingency_cents
    return design_fee_cents, contingency_cents, total


# --------------------------------------------- calculations.project_readiness_posture
def restricted_utilisation_cents(budget_ceiling_cents):
    return floor_int(Decimal(budget_ceiling_cents) * RESTRICTED_UTILISATION_PCT / Decimal(100))


def posture_for(open_critical, open_major, committed, ceiling):
    if open_critical > 0 or committed > ceiling:
        return "FROZEN"
    if open_major > 0 or committed > restricted_utilisation_cents(ceiling):
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------- calculations.ve_item_net_saving
def ve_net_saving(gross_saving_cents, rework_loss_pct, implementation_cost_cents):
    retained_exact = Decimal(gross_saving_cents) * (Decimal(1) - dec(rework_loss_pct) / Decimal(100))
    return half_up_int(retained_exact) - implementation_cost_cents


# ----------------------------------------------- calculations.show_scene_quality_score
def scene_quality(lighting, audio, animation, effects):
    total = (
        dec(lighting) * LIGHTING_WEIGHT
        + dec(audio) * AUDIO_WEIGHT
        + dec(animation) * ANIMATION_WEIGHT
        + dec(effects) * EFFECTS_WEIGHT
    )
    return half_up(total, 2)


# --------------------------------------------- calculations.project_show_quality_score
def project_show_quality(scenes):
    included = [s for s in scenes if s["status"] in ("PROGRAMMED", "VALIDATED") and s["scene_quality_score"] is not None]
    if not included:
        return ZERO_2DP
    numerator = Decimal(0)
    denominator = Decimal(0)
    for scene in included:
        numerator += dec(scene["scene_quality_score"]) * Decimal(scene["duration_seconds"])
        denominator += Decimal(scene["duration_seconds"])
    if denominator == 0:
        return ZERO_2DP
    return half_up(numerator / denominator, 2)


# ----------------------------------------- calculations.rehearsal_throughput_validation
def rehearsal_throughput(guests_cycled, duration_minutes, operational_capacity):
    measured = floor_int(Decimal(guests_cycled) * Decimal(60) / Decimal(duration_minutes))
    threshold = ceil_int(Decimal(operational_capacity) * REHEARSAL_PASS_PCT / Decimal(100))
    result = "PASS" if measured >= threshold else "FAIL"
    return measured, threshold, result


# ------------------------------------------------ calculations.spare_stock_recommendation
def spare_stock(criticality, annual_consumption_rate, lead_time_days):
    if criticality == "SHOW_CRITICAL":
        multiplier = Decimal("2.0")
        floor_qty = 2
    elif criticality == "RUN_CRITICAL":
        multiplier = Decimal("1.5")
        floor_qty = 1
    else:
        multiplier = Decimal("1.0")
        floor_qty = 0
    demand = dec(annual_consumption_rate) * Decimal(lead_time_days) / DAYS_PER_YEAR * multiplier
    return max(floor_qty, ceil_int(demand))
