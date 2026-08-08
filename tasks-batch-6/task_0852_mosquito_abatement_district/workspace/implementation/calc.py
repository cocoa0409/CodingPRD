"""Pinned arithmetic: surveillance indices, posture, volumes, and cost."""
from datetime import timedelta
from decimal import Decimal

import store
from common import D, q1, q2, rhu_int, logical_now

# --------------------------------------------------------------------------
# Constants (§ scaffold constants block / PRD §2.8, §3.5, §3.6, §3.9)
# --------------------------------------------------------------------------

SURVEILLANCE_WINDOW_DAYS = 14
ABUNDANCE_REFERENCE = D("50.0")
MIR_MULTIPLIER = D(1000)
MIR_REFERENCE = D("10.0")
LARVAL_REFERENCE = D("4.0")
DD_BASE_TEMP_C = D("10.0")
DD_REFERENCE = D("400.0")
W_ABUNDANCE = D("0.40")
W_INFECTION = D("0.35")
W_LARVAL = D("0.15")
W_WEATHER = D("0.10")
OUTBREAK_MULTIPLIER = D("1.25")
OUTBREAK_ABUNDANCE_TRIGGER = D("50.0")
POSTURE_ELEVATED_INDEX = D("40.0")
POSTURE_EMERGENCY_INDEX = D("70.0")
POSITIVE_ESCALATION_WINDOW_DAYS = 14
POOL_MAX_MOSQUITOES = 50
MAX_POOL_RETESTS = 2
TRAP_COLLECTION_MAX_AGE_DAYS = 7
WIND_DRIFT_TRIGGER_MPH = D("8.0")
WIND_DRIFT_FACTOR = D("1.10")
NO_DRIFT_FACTOR = D("1.00")
LABOR_RATE_CENTS_PER_MINUTE = 120
ADMIN_FEE_TIER1_MAX_CENTS = 100000
ADMIN_FEE_TIER2_MAX_CENTS = 500000
ADMIN_FEE_RATE_TIER1 = D("0.08")
ADMIN_FEE_RATE_TIER2 = D("0.06")
ADMIN_FEE_RATE_TIER3 = D("0.045")
ROUTE_SETUP_BUFFER_MINUTES = 45
AERIAL_NOTIFICATION_LEAD_HOURS = 48
GROUND_NOTIFICATION_LEAD_HOURS = 24
NOTIFICATION_ACK_WINDOW_HOURS = 24
NOTIFICATION_MAX_ATTEMPTS = 3
MAX_SEASONAL_APPLICATIONS = 2
REOPEN_WINDOW_DAYS = 30
SLA_HOURS = {"ROUTINE": 120, "PRIORITY": 48, "URGENT": 24}
SENSITIVE_SITE_BUFFER_METERS = {
    "APIARY": 1600,
    "ORGANIC_FARM": 800,
    "AQUACULTURE": 1600,
    "SCHOOL": 400,
}

POSTURE_RANK = {"NORMAL": 0, "ELEVATED": 1, "EMERGENCY": 2}
PRIORITY_RANK = {"ROUTINE": 0, "PRIORITY": 1, "URGENT": 2}
POSTURE_FLOOR = {"NORMAL": "ROUTINE", "ELEVATED": "PRIORITY", "EMERGENCY": "URGENT"}

LICENSE_COVERAGE = {
    "LARVICIDE_ONLY": ("LARVICIDE",),
    "ADULTICIDE": ("LARVICIDE", "ADULTICIDE"),
    "AERIAL": ("LARVICIDE", "ADULTICIDE", "AERIAL"),
}

OPEN_HANDLING_STATUSES = ("RECEIVED", "TRIAGED", "ASSIGNED", "INSPECTED")


# --------------------------------------------------------------------------
# Window helper
# --------------------------------------------------------------------------


def in_window(a_date, as_of_date, days=SURVEILLANCE_WINDOW_DAYS):
    """N-day window ending on as_of_date inclusive."""
    start = as_of_date - timedelta(days=days - 1)
    return start <= a_date <= as_of_date


# --------------------------------------------------------------------------
# Collection scoping helpers
# --------------------------------------------------------------------------


def trap_sites_of_area(area_id):
    return [t for t in store.TRAP_SITES.values() if t["service_area_id"] == area_id]


def collections_of_area(area_id):
    site_ids = set(t["id"] for t in trap_sites_of_area(area_id))
    return [c for c in store.TRAP_COLLECTIONS.values() if c["trap_site_id"] in site_ids]


def pools_of_collection(collection_id):
    return [p for p in store.LAB_POOLS.values()
            if p["trap_collection_id"] == collection_id]


# --------------------------------------------------------------------------
# trap_abundance_index
# --------------------------------------------------------------------------


def trap_abundance_index(area_id, as_of_date):
    total_females = 0
    total_trap_nights = 0
    for site in trap_sites_of_area(area_id):
        if not site.get("is_active"):
            continue
        for coll in store.TRAP_COLLECTIONS.values():
            if coll["trap_site_id"] != site["id"]:
                continue
            if coll["status"] not in ("SUBMITTED", "POOLED"):
                continue
            if not in_window(coll["collection_date"], as_of_date):
                continue
            total_females += coll["female_count"]
            total_trap_nights += coll["trap_nights"]
    if total_trap_nights == 0:
        return q2(0)
    return q2(D(total_females) / D(total_trap_nights))


# --------------------------------------------------------------------------
# larval_index
# --------------------------------------------------------------------------


def larval_index(area_id, as_of_date):
    total_dips = 0
    total_larvae = 0
    for insp in store.LARVAL_INSPECTIONS.values():
        if insp["service_area_id"] != area_id:
            continue
        if not in_window(insp["inspection_date"], as_of_date):
            continue
        total_dips += insp["dips"]
        total_larvae += insp["larvae_count"]
    if total_dips == 0:
        return q2(0)
    return q2(D(total_larvae) / D(total_dips))


# --------------------------------------------------------------------------
# degree days
# --------------------------------------------------------------------------


def observation_degree_day(tmax_c, tmin_c):
    raw = (D(tmax_c) + D(tmin_c)) / D(2) - DD_BASE_TEMP_C
    rounded = q1(raw)
    if rounded < 0:
        return q1(0)
    return rounded


def degree_day_accumulation(area, as_of_date):
    season_start = area["season_start_date"]
    rows = []
    for obs in store.WEATHER_OBSERVATIONS.values():
        if obs["service_area_id"] != area["id"]:
            continue
        if obs["obs_date"] < season_start or obs["obs_date"] > as_of_date:
            continue
        rows.append(obs)
    rows.sort(key=lambda o: (o["obs_date"], o["created_at"], o["_seq"]))
    total = Decimal("0.0")
    for obs in rows:
        total += D(obs["degree_day"])
    return q1(total)


# --------------------------------------------------------------------------
# minimum_infection_rate
# --------------------------------------------------------------------------

_MIR_STATUSES = {
    "PROVISIONAL": ("IN_TESTING", "RESULT_POSITIVE", "RESULT_NEGATIVE"),
    "CONFIRMED": ("RESULT_POSITIVE", "RESULT_NEGATIVE"),
}


def minimum_infection_rate(area_id, as_of_date, variant):
    allowed = _MIR_STATUSES[variant]
    candidate_collection_ids = set()
    for coll in collections_of_area(area_id):
        if coll["status"] not in ("SUBMITTED", "POOLED"):
            continue
        if not in_window(coll["collection_date"], as_of_date):
            continue
        candidate_collection_ids.add(coll["id"])
    total_mosquitoes = 0
    positive_pools = 0
    for pool in store.LAB_POOLS.values():
        if pool["trap_collection_id"] not in candidate_collection_ids:
            continue
        if pool["status"] not in allowed:
            continue
        total_mosquitoes += pool["pool_size"]
        if pool["status"] == "RESULT_POSITIVE":
            positive_pools += 1
    if total_mosquitoes == 0:
        return q2(0)
    return q2(D(positive_pools) / D(total_mosquitoes) * MIR_MULTIPLIER)


# --------------------------------------------------------------------------
# vector_index
# --------------------------------------------------------------------------


def _component(raw, reference):
    value = q2(D(raw) / D(reference) * D(100))
    if value > D("100.00"):
        return D("100.00")
    return value


def vector_index(abundance_index_value, mir_value, larval_index_value, degree_days_value):
    abundance_component = _component(abundance_index_value, ABUNDANCE_REFERENCE)
    infection_component = _component(mir_value, MIR_REFERENCE)
    larval_component = _component(larval_index_value, LARVAL_REFERENCE)
    weather_component = _component(degree_days_value, DD_REFERENCE)

    base = (W_ABUNDANCE * abundance_component
            + W_INFECTION * infection_component
            + W_LARVAL * larval_component
            + W_WEATHER * weather_component)

    if infection_component > D("0.00") and abundance_component >= OUTBREAK_ABUNDANCE_TRIGGER:
        base = base * OUTBREAK_MULTIPLIER

    result = q2(base)
    if result > D("100.00"):
        return D("100.00")
    return result


# --------------------------------------------------------------------------
# area_risk_posture
# --------------------------------------------------------------------------


def has_recent_positive(area_id, now=None):
    now = now or logical_now()
    horizon = now - timedelta(days=POSITIVE_ESCALATION_WINDOW_DAYS)
    collection_ids = set(c["id"] for c in collections_of_area(area_id))
    for pool in store.LAB_POOLS.values():
        if pool["status"] != "RESULT_POSITIVE":
            continue
        if pool["trap_collection_id"] not in collection_ids:
            continue
        recorded = pool.get("result_recorded_at")
        if recorded is not None and recorded >= horizon:
            return True
    return False


def area_ever_confirmed(area_id):
    for assessment in store.RISK_ASSESSMENTS.values():
        if assessment["service_area_id"] != area_id:
            continue
        if assessment.get("confirmed_at") is not None:
            return True
    return False


def derive_posture(area):
    index_value = D(area["latest_confirmed_vector_index"])
    if index_value >= POSTURE_EMERGENCY_INDEX:
        index_posture = "EMERGENCY"
    elif index_value >= POSTURE_ELEVATED_INDEX:
        index_posture = "ELEVATED"
    else:
        index_posture = "NORMAL"

    override_posture = "ELEVATED" if has_recent_positive(area["id"]) else "NORMAL"

    if POSTURE_RANK[override_posture] > POSTURE_RANK[index_posture]:
        posture = override_posture
        source = "POSITIVE_OVERRIDE"
    else:
        posture = index_posture
        if not area_ever_confirmed(area["id"]):
            source = "NO_ASSESSMENT"
        else:
            source = "INDEX"
    return posture, source


# --------------------------------------------------------------------------
# service_request_due_at
# --------------------------------------------------------------------------


def service_request_due_at(triaged_at, priority):
    if triaged_at is None:
        return None
    return triaged_at + timedelta(hours=SLA_HOURS[priority])


# --------------------------------------------------------------------------
# sensitive_site_encroachment
# --------------------------------------------------------------------------


def separation_distance(route, site):
    dx = D(route["center_x_m"] - site["x_m"])
    dy = D(route["center_y_m"] - site["y_m"])
    return q2((dx * dx + dy * dy).sqrt())


def encroaches(route, site):
    limit = D(site["buffer_meters"] + route.get("swath_radius_m", 0))
    return separation_distance(route, site) <= limit


# --------------------------------------------------------------------------
# route_pesticide_volume
# --------------------------------------------------------------------------


def estimated_volume(planned_acres, label_rate):
    return q2(D(planned_acres) * D(label_rate))


def actual_volume(actual_acres, label_rate, wind_speed_mph):
    factor = WIND_DRIFT_FACTOR if D(wind_speed_mph) >= WIND_DRIFT_TRIGGER_MPH else NO_DRIFT_FACTOR
    return q2(D(actual_acres) * D(label_rate) * factor)


# --------------------------------------------------------------------------
# plan_estimated_total_ml
# --------------------------------------------------------------------------


def plan_estimated_total_ml(plan_id):
    total = Decimal("0.00")
    for route in store.TREATMENT_ROUTES.values():
        if route["treatment_plan_id"] != plan_id:
            continue
        if route["status"] not in ("COMMITTED", "EXECUTED", "VERIFIED"):
            continue
        total += D(route["estimated_volume_ml"])
    return q2(total)


# --------------------------------------------------------------------------
# treatment_cost_allocation
# --------------------------------------------------------------------------


def treatment_cost_allocation(plan_id):
    material_cost_cents = 0
    labor_cost_cents = 0
    for route in store.TREATMENT_ROUTES.values():
        if route["treatment_plan_id"] != plan_id:
            continue
        if route["status"] != "VERIFIED":
            continue
        product = store.PESTICIDE_PRODUCTS.get(route["pesticide_product_id"])
        actual = D(route.get("actual_volume_ml") or 0)
        cents_per_liter = D(product["cost_cents_per_liter"]) if product else D(0)
        material_cost_cents += rhu_int(actual / D(1000) * cents_per_liter)
        labor_cost_cents += route["duration_minutes"] * LABOR_RATE_CENTS_PER_MINUTE

    subtotal_cents = material_cost_cents + labor_cost_cents
    if subtotal_cents < ADMIN_FEE_TIER1_MAX_CENTS:
        admin_fee_rate = ADMIN_FEE_RATE_TIER1
    elif subtotal_cents < ADMIN_FEE_TIER2_MAX_CENTS:
        admin_fee_rate = ADMIN_FEE_RATE_TIER2
    else:
        admin_fee_rate = ADMIN_FEE_RATE_TIER3
    admin_fee_cents = rhu_int(D(subtotal_cents) * admin_fee_rate)
    total_cost_cents = subtotal_cents + admin_fee_cents
    return {
        "material_cost_cents": material_cost_cents,
        "labor_cost_cents": labor_cost_cents,
        "subtotal_cents": subtotal_cents,
        "admin_fee_rate": admin_fee_rate,
        "admin_fee_cents": admin_fee_cents,
        "total_cost_cents": total_cost_cents,
    }
