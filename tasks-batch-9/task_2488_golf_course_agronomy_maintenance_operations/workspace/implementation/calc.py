"""The ten pinned calculations (PRD section 4 / SCAFFOLD calculations)."""

from datetime import date, timedelta
from decimal import Decimal

from errors import ApiError
from store import clock, store
from util import ZERO, dec, dmin, rhu, whole_minutes

SQ_FT_PER_ACRE = Decimal(43560)
GAL_PER_PCT_PER_1000_SQ_FT = Decimal("6.2")

MAX_N_LB_PER_1000_BY_AREA_TYPE = {
    "GREEN": Decimal("4.00"),
    "PRACTICE_GREEN": Decimal("4.00"),
    "TEE": Decimal("5.00"),
    "APPROACH": Decimal("5.00"),
    "FAIRWAY": Decimal("6.00"),
    "ROUGH": Decimal("3.00"),
}

POSTURE_FACTOR = {
    "OPEN": Decimal("1.00"),
    "RESTRICTED": Decimal("0.60"),
    "SUSPENDED": Decimal("0.00"),
}

WATER_BASE_RATE_PER_1000 = Decimal("3.25")
WATER_TIER_RATE = {
    "T1": Decimal("0.90"),
    "T2": Decimal("1.40"),
    "T3": Decimal("2.10"),
}

REPLACEMENT_FLAG_THRESHOLD = Decimal("70")
READINESS_CERTIFY_THRESHOLD = Decimal("82.00")

TARGET_GREEN_SPEED = Decimal("11.0")
GREEN_SPEED_TOLERANCE = Decimal("1.5")
TARGET_FIRMNESS = Decimal("1.35")
FIRMNESS_TOLERANCE = Decimal("0.30")
TARGET_MOISTURE = Decimal("18.0")
MOISTURE_TOLERANCE = Decimal("6.0")

SHOTGUN_EVENT_TYPE = "SHOTGUN_START"
FROST_STAGGER_MINUTES = 10
HOLE_PACE_MINUTES = 12
PLAY_CLEARANCE_MINUTES = 30


# ==========================================================================
# 1. plan_nitrogen_commitment_lb
# ==========================================================================
def task_commitment_lb(task_type, nitrogen_lb_per_1000, area_sq_ft):
    if task_type != "FERTILITY" or nitrogen_lb_per_1000 is None:
        return Decimal("0.00")
    thousands = dec(area_sq_ft) / Decimal(1000)
    return rhu(dec(nitrogen_lb_per_1000) * thousands, 2)


def plan_committed_nitrogen_lb(plan_id):
    """Sum of ALREADY-ROUNDED task commitments; the sum is re-rounded to 2dp."""
    total = ZERO
    for task in store.plan_tasks.values():
        if task["plan_id"] != plan_id:
            continue
        if task["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        total += dec(task["commitment_lb"])
    return rhu(total, 2)


# ==========================================================================
# 2. turf_nitrogen_load
# ==========================================================================
def turf_nitrogen_applied(area):
    thousands = dec(area["area_sq_ft"]) / Decimal(1000)
    year = clock().year
    total = ZERO
    for app in store.applications.values():
        if app["turf_area_id"] != area["id"]:
            continue
        if app["record_status"] not in ("RECORDED", "VERIFIED"):
            continue
        if app["applied_at"].year != year:
            continue
        total += rhu(dec(app["nitrogen_lb"]) / thousands, 3)
    return rhu(total, 3)


def turf_nitrogen_planned(area):
    total = ZERO
    for task in store.plan_tasks.values():
        if task["turf_area_id"] != area["id"]:
            continue
        if task["task_type"] != "FERTILITY":
            continue
        if task["status"] not in ("PLANNED", "SCHEDULED"):
            continue
        if task["nitrogen_lb_per_1000"] is None:
            continue
        total += dec(task["nitrogen_lb_per_1000"])
    return total


def turf_nitrogen_load(area):
    applied = turf_nitrogen_applied(area)
    projected = rhu(applied + turf_nitrogen_planned(area), 3)
    return applied, projected


def turf_nitrogen_ceiling(area):
    return MAX_N_LB_PER_1000_BY_AREA_TYPE[area["area_type"]]


# ==========================================================================
# 3. application_mass_and_nitrogen
# ==========================================================================
def application_mass_and_nitrogen(rate_lb_per_acre, area_sq_ft, nitrogen_pct,
                                  applied_at, rei_hours):
    acres = dec(area_sq_ft) / SQ_FT_PER_ACRE
    total_lb = rhu(dec(rate_lb_per_acre) * acres, 2)
    nitrogen_lb = rhu(total_lb * (dec(nitrogen_pct) / Decimal(100)), 2)
    rei_expires_at = applied_at + timedelta(hours=int(rei_hours))
    return total_lb, nitrogen_lb, rei_expires_at


# ==========================================================================
# 4. irrigation_run_allotment
# ==========================================================================
def irrigation_allotment(area, station, course, window_start, window_end, deficit_pct):
    duration = whole_minutes(window_start, window_end)
    thousands = dec(area["area_sq_ft"]) / Decimal(1000)
    gross_gal = dec(deficit_pct) * thousands * GAL_PER_PCT_PER_1000_SQ_FT
    factor = POSTURE_FACTOR[course["water_posture"]]
    headroom = dec(station["daily_withdrawal_cap_gal"]) - dec(station["withdrawn_today_gal"])
    if headroom < ZERO:
        headroom = ZERO
    allotted_gal = rhu(dmin(gross_gal * factor, headroom), 1)
    flow_gpm = rhu(allotted_gal / Decimal(duration), 2)
    return duration, allotted_gal, flow_gpm


def irrigation_volume(run, actual_minutes=None):
    duration = whole_minutes(run["window_start"], run["window_end"])
    if actual_minutes is None:
        actual_minutes = duration
    return rhu(dec(run["allotted_gal"]) * dec(actual_minutes) / Decimal(duration), 1)


# ==========================================================================
# 5. course_water_posture
# ==========================================================================
def course_water_posture(course):
    allocation = dec(course["annual_water_allocation_gal"])
    used = dec(course["water_used_gal"])
    if allocation <= ZERO:
        return "SUSPENDED"
    scaled = used * Decimal(100)
    if scaled >= dec(course["water_suspended_threshold_pct"]) * allocation:
        return "SUSPENDED"
    if scaled >= dec(course["water_restricted_threshold_pct"]) * allocation:
        return "RESTRICTED"
    return "OPEN"


# ==========================================================================
# 6. water_overage_assessment
# ==========================================================================
def water_overage_assessment(course):
    used = dec(course["water_used_gal"])
    allocation = dec(course["annual_water_allocation_gal"])
    billable_gal = used - allocation
    if billable_gal < ZERO:
        billable_gal = ZERO
    base_charge = rhu(used / Decimal(1000) * WATER_BASE_RATE_PER_1000, 2)
    if base_charge < Decimal("25.00"):
        tier = "T1"
    elif base_charge < Decimal("100.00"):
        tier = "T2"
    else:
        tier = "T3"
    rate = WATER_TIER_RATE[tier]
    surcharge = rhu(billable_gal / Decimal(1000) * rate, 2)
    total_charge = rhu(base_charge + surcharge, 2)
    return {
        "billable_gal": float(rhu(billable_gal, 1)),
        "base_charge": float(base_charge),
        "tier": tier,
        "surcharge_rate": float(rate),
        "surcharge": float(surcharge),
        "total_charge": float(total_charge),
    }


# ==========================================================================
# 7. equipment_replacement_score
# ==========================================================================
def _score(usage_ratio, age_ratio, overdue_ratio):
    raw = Decimal(100) * (
        Decimal("0.45") * dmin(usage_ratio, Decimal(1))
        + Decimal("0.35") * dmin(age_ratio, Decimal(1))
        + Decimal("0.20") * dmin(overdue_ratio, Decimal(1))
    )
    value = rhu(raw, 1)
    if value < ZERO:
        return Decimal("0.0")
    if value > Decimal(100):
        return Decimal("100.0")
    return value


def equipment_replacement_score(unit):
    now = clock()
    age_years = Decimal(now.year - int(unit["model_year"]))
    if age_years < ZERO:
        age_years = ZERO
    expected_life = dec(unit["expected_life_hours"])
    engine_hours = dec(unit["engine_hours"])
    usage_now = engine_hours / expected_life
    days_to_fy_end = (date(now.year, 12, 31) - now.date()).days
    if days_to_fy_end < 0:
        days_to_fy_end = 0
    projected_hours = engine_hours + dec(unit["avg_daily_hours"]) * Decimal(days_to_fy_end)
    usage_projected = projected_hours / expected_life
    overdue = dec(unit["hours_since_service"]) / dec(unit["service_interval_hours"])
    age_ratio = age_years / Decimal(10)
    score = _score(usage_now, age_ratio, overdue)
    projected = _score(usage_projected, age_ratio, overdue)
    return score, projected, projected >= REPLACEMENT_FLAG_THRESHOLD


# ==========================================================================
# 8. tournament_readiness_index
# ==========================================================================
def _band_score(value, target, tolerance):
    deviation = abs(dec(value) - target) / tolerance
    return Decimal(100) - dmin(deviation, Decimal(1)) * Decimal(100)


def reading_within_tournament_spec(green_speed_ft, firmness_gravities):
    speed_ok = abs(dec(green_speed_ft) - TARGET_GREEN_SPEED) <= GREEN_SPEED_TOLERANCE
    firm_ok = abs(dec(firmness_gravities) - TARGET_FIRMNESS) <= FIRMNESS_TOLERANCE
    return bool(speed_ok and firm_ok)


def latest_reading(area_id, window_start=None, window_end=None):
    best = None
    for reading in store.readings.values():
        if reading["turf_area_id"] != area_id:
            continue
        measured = reading["measured_at"]
        if window_start is not None and measured < window_start:
            continue
        if window_end is not None and measured > window_end:
            continue
        key = (measured, reading["created_at"], reading["_seq"])
        if best is None or key > best[0]:
            best = (key, reading)
    return best[1] if best else None


def tournament_readiness_index(event):
    window_start = event["start_at"] - timedelta(hours=24)
    window_end = event["start_at"]
    per_area = []
    areas = [
        area for area in store.turf_areas.values()
        if area["course_id"] == event["course_id"]
        and area["area_type"] == "GREEN"
        and area["agronomic_status"] == "ACTIVE"
    ]
    areas.sort(key=lambda a: a["_seq"])
    for area in areas:
        reading = latest_reading(area["id"], window_start, window_end)
        if reading is None:
            continue
        speed = _band_score(reading["green_speed_ft"], TARGET_GREEN_SPEED, GREEN_SPEED_TOLERANCE)
        firm = _band_score(reading["firmness_gravities"], TARGET_FIRMNESS, FIRMNESS_TOLERANCE)
        moist = _band_score(reading["moisture_pct"], TARGET_MOISTURE, MOISTURE_TOLERANCE)
        area_index = rhu(
            Decimal("0.50") * speed + Decimal("0.30") * firm + Decimal("0.20") * moist, 2
        )
        per_area.append((area, reading, area_index))
    if len(per_area) < 3:
        raise ApiError("ERR_INSUFFICIENT_READINGS")
    total = ZERO
    for _, _, area_index in per_area:
        total += area_index
    readiness_index = rhu(total / Decimal(len(per_area)), 2)
    status = "CERTIFIED" if readiness_index >= READINESS_CERTIFY_THRESHOLD else "FAILED"
    return readiness_index, status, per_area


# ==========================================================================
# 9. frost_release_schedule
# ==========================================================================
def frost_release_schedule(course_id, delay_minutes, expected_clear_at):
    """Returns the ordered list of (event, effective_start_at, delayed_minutes)."""
    candidates = [
        event for event in store.play_events.values()
        if event["course_id"] == course_id
        and event["status"] == "SCHEDULED"
        and event["start_at"] < expected_clear_at
    ]
    candidates.sort(key=lambda e: (e["start_at"], e["created_at"], e["_seq"]))
    result = []
    previous_effective = None
    for event in candidates:
        naive = event["start_at"] + timedelta(minutes=int(delay_minutes))
        if event["event_type"] == SHOTGUN_EVENT_TYPE:
            effective = naive
        else:
            if previous_effective is None:
                effective = naive
            else:
                floor = previous_effective + timedelta(minutes=FROST_STAGGER_MINUTES)
                effective = naive if naive >= floor else floor
            previous_effective = effective
        delayed = int((effective - event["start_at"]).total_seconds() // 60)
        result.append((event, effective, delayed))
    return result


# ==========================================================================
# 10. course_play_posture
# ==========================================================================
def course_play_posture(course_id):
    active = [
        event for event in store.weather_events.values()
        if event["course_id"] == course_id and event["status"] == "ACTIVE"
    ]
    if any(e["event_type"] in ("LIGHTNING", "STORM_DAMAGE") for e in active):
        return "CLOSED", 0
    frosts = [e for e in active if e["event_type"] == "FROST"]
    if frosts:
        governing = max(frosts, key=lambda e: (e["declared_at"], e["created_at"], e["_seq"]))
        return "FROST_DELAY", int(governing["delay_minutes"] or 0)
    if any(e["event_type"] == "HEAVY_RAIN" for e in active):
        return "CART_PATH_ONLY", 0
    return "OPEN", 0


# ==========================================================================
# applicator license status (computed field)
# ==========================================================================
def license_status(applicator):
    if applicator.get("suspended_at") is not None:
        return "SUSPENDED"
    if applicator["license_expires_on"] < clock().date():
        return "EXPIRED"
    return "ACTIVE"
