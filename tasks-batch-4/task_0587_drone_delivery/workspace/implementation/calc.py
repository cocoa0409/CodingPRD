"""Calculations (PRD 2.7, 2.8, 3.2, 3.3, 3.4, 3.6, 3.9).

All arithmetic runs on Decimal; rounding is half-up everywhere.
"""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from db import db

# --- geodesy (PRD 2.7) ----------------------------------------------------
KM_PER_DEG_LAT = Decimal("111.0")
KM_PER_DEG_LON = Decimal("85.0")

# --- fee tiers (PRD 3.3) --------------------------------------------------
TIER1_MAX_KM = Decimal("5.0")
TIER1_BASE = Decimal("4.00")
TIER2_MAX_KM = Decimal("12.0")
TIER2_BASE = Decimal("6.50")
TIER3_BASE = Decimal("9.00")
PAYLOAD_RATE_PER_KG = Decimal("0.90")
PRIORITY_MULT = {
    "STANDARD": Decimal("1.0"),
    "URGENT": Decimal("1.35"),
    "MEDICAL": Decimal("1.60"),
}

# --- surcharge tiers (PRD 3.3) -------------------------------------------
SURCHARGE_TIER1_MAX = Decimal("8.00")
SURCHARGE_TIER2_MAX = Decimal("15.00")
SURCHARGE_PCT_LOW = Decimal("0.05")
SURCHARGE_PCT_MID = Decimal("0.08")
SURCHARGE_PCT_HIGH = Decimal("0.12")

# --- energy (PRD 3.4, 3.7) ------------------------------------------------
ENERGY_PCT_PER_KM = Decimal("1.6")
PAYLOAD_ENERGY_FACTOR = Decimal("0.08")
WIND_FREE_KPH = Decimal("10.0")
WIND_PENALTY_PER_KPH = Decimal("0.02")
HOVER_PCT = Decimal("3.0")
RESERVE_PCT = Decimal("15.0")

# --- pad hold (PRD 3.4) ---------------------------------------------------
PAD_BUFFER_MIN = 5
PAD_HOLD_MIN = 10
HOVER_MIN = 3

# --- risk (PRD 3.2) -------------------------------------------------------
SERVICE_WEIGHT = Decimal("40.0")
SERVICE_INTERVAL_H = Decimal("50.0")
CYCLE_WEIGHT = Decimal("30.0")
RETIRE_CYCLES = Decimal("300")
SEVERITY_POINTS = {"MINOR": Decimal("5"), "MAJOR": Decimal("15"), "CRITICAL": Decimal("30")}
SEVERITY_CAP = Decimal("30")
RISK_BLOCK_THRESHOLD = Decimal("70.0")

# --- weather (PRD 3.1) ----------------------------------------------------
MAX_WIND_KPH = Decimal("35.0")
MAX_GUST_KPH = Decimal("45.0")
MIN_VISIBILITY_KM = Decimal("1.5")

ADVISORY_BUCKET = ("CLOSED",)
BLOCKING_BUCKET = ("OPEN", "UNDER_REVIEW", "MAINTENANCE_REQUIRED", "CLOSED")


def rhu(value, places):
    """Round half up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def planar_distance_km(lat_a, lon_a, lat_b, lon_b):
    dy = (Decimal(lat_b) - Decimal(lat_a)) * KM_PER_DEG_LAT
    dx = (Decimal(lon_b) - Decimal(lon_a)) * KM_PER_DEG_LON
    return rhu((dy * dy + dx * dx).sqrt(), 3)


# --- order intake ---------------------------------------------------------


def delivery_fee(distance_km, payload_weight_g, priority):
    if distance_km <= TIER1_MAX_KM:
        base = TIER1_BASE
    elif distance_km <= TIER2_MAX_KM:
        base = TIER2_BASE
    else:
        base = TIER3_BASE
    payload = (Decimal(payload_weight_g) / Decimal("1000")) * PAYLOAD_RATE_PER_KG
    subtotal = rhu(base, 2) + rhu(payload, 2)
    return rhu(subtotal * PRIORITY_MULT[priority], 2)


def billing_total(fee):
    if fee <= SURCHARGE_TIER1_MAX:
        pct = SURCHARGE_PCT_LOW
    elif fee <= SURCHARGE_TIER2_MAX:
        pct = SURCHARGE_PCT_MID
    else:
        pct = SURCHARGE_PCT_HIGH
    surcharge = rhu(pct * fee, 2)
    return surcharge, rhu(fee + surcharge, 2)


# --- energy ---------------------------------------------------------------


def _core(route_km, payload_weight_g, wind_kph):
    payload_factor = Decimal(1) + (Decimal(payload_weight_g) / Decimal("1000")) * PAYLOAD_ENERGY_FACTOR
    excess = Decimal(wind_kph) - WIND_FREE_KPH
    if excess < 0:
        excess = Decimal(0)
    wind_factor = Decimal(1) + excess * WIND_PENALTY_PER_KPH
    return Decimal(route_km) * ENERGY_PCT_PER_KM * payload_factor * wind_factor


def required_energy_pct(planned_route_km, payload_weight_g, wind_kph):
    """Provisional variant: hover + planning reserve."""
    return rhu(_core(planned_route_km, payload_weight_g, wind_kph) + HOVER_PCT + RESERVE_PCT, 1)


def actual_energy_pct(actual_route_km, payload_weight_g, wind_kph):
    """Actual variant: hover only, the 15.0 reserve is never consumed."""
    return rhu(_core(actual_route_km, payload_weight_g, wind_kph) + HOVER_PCT, 1)


def cruise_minutes(planned_route_km, cruise_speed_kmh):
    """Cruise leg in whole minutes, rounded UP (PRD 3.4)."""
    minutes = (Decimal(planned_route_km) / Decimal(cruise_speed_kmh)) * Decimal(60)
    return int(minutes.quantize(Decimal(1), rounding=ROUND_CEILING))


def flight_hours_delta(actual_route_km, cruise_speed_kmh):
    return rhu(Decimal(actual_route_km) / Decimal(cruise_speed_kmh), 2)


# --- battery health (PRD 3.2) --------------------------------------------


def health_pct(cycle_count):
    value = Decimal(100) - (Decimal(cycle_count) / RETIRE_CYCLES) * Decimal(100)
    value = rhu(value, 1)
    if value < 0:
        value = Decimal("0.0")
    return value


# --- airworthiness risk (PRD 3.2) ----------------------------------------


def _severity_points(drone_id, bucket):
    total = Decimal(0)
    for inc in db.incidents.values():
        if inc["drone_id"] == drone_id and inc["status"] in bucket:
            total += SEVERITY_POINTS[inc["severity"]]
    return min(SEVERITY_CAP, total)


def _base_terms(drone):
    ratio = Decimal(drone["hours_since_service"]) / SERVICE_INTERVAL_H
    if ratio > 1:
        ratio = Decimal(1)
    service_term = SERVICE_WEIGHT * ratio

    battery_id = drone.get("installed_battery_id")
    battery = db.batteries.get(battery_id) if battery_id else None
    if battery is None:
        cycle_term = CYCLE_WEIGHT
    else:
        cratio = Decimal(battery["cycle_count"]) / RETIRE_CYCLES
        if cratio > 1:
            cratio = Decimal(1)
        cycle_term = CYCLE_WEIGHT * cratio
    return service_term + cycle_term


def advisory_risk_score(drone):
    return rhu(_base_terms(drone) + _severity_points(drone["id"], ADVISORY_BUCKET), 1)


def blocking_risk_score(drone):
    return rhu(_base_terms(drone) + _severity_points(drone["id"], BLOCKING_BUCKET), 1)


# --- weather (PRD 3.1) ----------------------------------------------------


def flyable(wind_kph, gust_kph, visibility_km, precip):
    return (
        Decimal(wind_kph) <= MAX_WIND_KPH
        and Decimal(gust_kph) <= MAX_GUST_KPH
        and Decimal(visibility_km) >= MIN_VISIBILITY_KM
        and precip in ("NONE", "LIGHT")
    )


def latest_observation(service_area_id):
    """Greatest observed_at; ties broken by greatest created_at (then insertion)."""
    rows = [o for o in db.weather_observations.values() if o["service_area_id"] == service_area_id]
    if not rows:
        return None
    return max(rows, key=lambda o: (o["observed_at"], o["created_at"], o["_seq"]))
