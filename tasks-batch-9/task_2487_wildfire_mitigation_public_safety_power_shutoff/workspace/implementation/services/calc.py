"""Deterministic calculations (PRD 3.x / scaffold calculations C1-C15)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import clock
import db
from errors import ApiError

ZERO = Decimal("0")
ONE = Decimal("1")

# ------------------------------------------------------------------ constants
COVERED_CONDUCTOR_EFFECTIVENESS = Decimal("0.6")
UNDERGROUND_EFFECTIVENESS = Decimal("1.0")

WIND_WEIGHT = Decimal("0.35")
DRYNESS_WEIGHT = Decimal("0.30")
TERRAIN_WEIGHT = Decimal("0.20")
EQUIPMENT_WEIGHT = Decimal("0.15")
HARDENING_CREDIT_FACTOR = Decimal("0.40")
DEGRADED_WEIGHT_FACTOR = Decimal("0.5")
INSPECTION_OVERDUE_PENALTY = Decimal("30")
WIND_THRESHOLD_MPH = Decimal("20")
WIND_SLOPE = Decimal("2.5")
DFM_REFERENCE_PCT = Decimal("12")
DFM_SLOPE = Decimal("4")
OBSERVATION_WINDOW_HOURS = 24

TERRAIN_POINTS = {
    "TIER_3": Decimal("100"),
    "TIER_2": Decimal("70"),
    "TIER_1": Decimal("40"),
    "NON_HFTD": Decimal("10"),
}

FPI_TIER_BREAKS = [
    (Decimal("20"), "R1"),
    (Decimal("40"), "R2"),
    (Decimal("60"), "R3"),
    (Decimal("75"), "R4"),
]

MEDICAL_BASELINE_WEIGHT = Decimal("4")
CRITICAL_FACILITY_WEIGHT = Decimal("10")
IMPACT_DIVISOR = Decimal("10")
MIN_NET_BENEFIT_RATIO = Decimal("0.25")
MIN_ADJUSTED_IMPACT = Decimal("0.01")

CRC_CREDIT_BANDS = [
    (Decimal("20"), Decimal("0.00")),
    (Decimal("60"), Decimal("0.05")),
    (Decimal("200"), Decimal("0.12")),
]
CRC_CREDIT_TOP_RATE = Decimal("0.20")
CRC_RESET_BUFFER_MINUTES = 240

STAGE_MIN_LEAD_MINUTES = {
    "ADVANCE_48H": 2880,
    "ADVANCE_24H": 1440,
    "IMMINENT_1H": 60,
    "ACTIVATION": 0,
    "RESTORATION": 0,
}
PRE_ONSET_STAGES = ("ADVANCE_48H", "ADVANCE_24H", "IMMINENT_1H")
CHANNEL_PRIORITY = ("SMS", "VOICE", "EMAIL")
FORBIDDEN_CHANNELS = {"TTY": ("VOICE",), "AUDIO": ("SMS", "EMAIL")}
FULL_LANGUAGES = ("EN", "ES", "ZH", "TL", "VI")
RESTRICTED_LANGUAGES = ("EN", "ES")
RESTRICTED_LANGUAGE_STAGES = ("IMMINENT_1H", "ACTIVATION")
TIER_RANK = {"TIER_A_CRITICAL": 0, "TIER_B_MEDICAL": 1, "TIER_C_STANDARD": 2}
CRITICAL_TIERS = ("TIER_A_CRITICAL", "TIER_B_MEDICAL")

PROGRAM_EFFECTIVENESS = {
    "COVERED_CONDUCTOR": Decimal("0.62"),
    "UNDERGROUNDING": Decimal("1.00"),
    "FAST_TRIP_SETTING": Decimal("0.45"),
    "INSPECTION_CYCLE": Decimal("0.18"),
}
HFTD_RISK_MULTIPLIER = {
    "TIER_3": Decimal("1.5"),
    "TIER_2": Decimal("1.2"),
    "TIER_1": Decimal("1.0"),
    "NON_HFTD": Decimal("0.5"),
}

HARDENING_PROGRAMS = ("COVERED_CONDUCTOR", "UNDERGROUNDING")
LEDGER_STATUSES = ("IN_EXECUTION", "SUSPENDED", "COMPLETED")
QUALIFYING_FILING_STATUSES = ("APPROVED", "IN_EXECUTION", "SUSPENDED", "COMPLETED")
UNDERGROUND_TARGET_MILES = Decimal("20.0")
COVERED_CONDUCTOR_TARGET_MILES = Decimal("50.0")
LEAD_TARGET_MINUTES = Decimal("2880")
INSPECTION_MONTH_DAYS = 30

LOCKED_ENERGIZATION_STATES = (
    "DE_ENERGIZATION_PENDING",
    "DE_ENERGIZED",
    "PATROL_IN_PROGRESS",
    "CLEARED_FOR_RESTORE",
)
LIVE_EVENT_STATES = ("SCOPED", "ARMED", "ACTIVE", "RESTORING")


# ------------------------------------------------------------------- numerics
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    exponent = Decimal(1).scaleb(-places)
    return D(value).quantize(exponent, rounding=ROUND_HALF_UP)


def q(value, places):
    return rhu(value, places)


def clamp(value, low, high):
    value = D(value)
    if value < D(low):
        return D(low)
    if value > D(high):
        return D(high)
    return value


def seconds_between(start, end):
    delta = end - start
    return (
        Decimal(delta.days) * Decimal(86400)
        + Decimal(delta.seconds)
        + Decimal(delta.microseconds) / Decimal(1000000)
    )


def floor_minutes(start, end):
    """floor((end - start) / 60 seconds); floors toward negative infinity."""
    secs = seconds_between(start, end)
    return int((secs / Decimal(60)).to_integral_value(rounding=ROUND_FLOOR))


def ceil_hours(start, end):
    secs = seconds_between(start, end)
    return int((secs / Decimal(3600)).to_integral_value(rounding=ROUND_CEILING))


# ----------------------------------------------------- C1 / circuit roll-ups
def circuit_projects(circuit):
    return [
        p for p in db.mitigation_projects.values() if p["circuit_id"] == circuit["id"]
    ]


def recompute_hardened_mileage(circuit):
    """C15 ledger + C1 hardened_fraction, derived from the project rows."""
    covered = ZERO
    underground = ZERO
    for project in circuit_projects(circuit):
        if project["status"] not in LEDGER_STATUSES:
            continue
        if project["program_type"] == "COVERED_CONDUCTOR":
            covered += D(project["completed_miles"])
        elif project["program_type"] == "UNDERGROUNDING":
            underground += D(project["completed_miles"])
    circuit["covered_conductor_miles"] = q(covered, 1)
    circuit["underground_miles"] = q(underground, 1)
    raw = (
        covered * COVERED_CONDUCTOR_EFFECTIVENESS + underground * UNDERGROUND_EFFECTIVENESS
    ) / D(circuit["overhead_miles"])
    fraction = rhu(raw, 4)
    if fraction > ONE:
        fraction = Decimal("1.0000")
    circuit["hardened_fraction"] = fraction
    return fraction


def recompute_customer_counts(circuit):
    total = 0
    medical = 0
    critical = 0
    for customer in db.customers.values():
        if customer["circuit_id"] != circuit["id"]:
            continue
        total += 1
        if customer["medical_baseline"]:
            medical += 1
        if customer["customer_class"] == "CRITICAL_FACILITY":
            critical += 1
    circuit["customer_count"] = total
    circuit["medical_baseline_count"] = medical
    circuit["critical_facility_count"] = critical


# ---------------------------------------------------------------- C2 the index
def fpi_tier(score):
    score = D(score)
    for break_point, tier in FPI_TIER_BREAKS:
        if score < break_point:
            return tier
    return "R5"


def inspection_overdue(circuit, now=None):
    last = circuit.get("last_inspection_completed_at")
    if last is None:
        return True
    now = now or clock.now()
    due = last + timedelta(days=INSPECTION_MONTH_DAYS * int(circuit["inspection_cycle_months"]))
    return now >= due


def station_observations(station, window_start, window_end):
    return [
        o
        for o in db.weather_observations.values()
        if o["weather_station_id"] == station["id"]
        and window_start <= o["observed_at"] < window_end
    ]


def compute_fire_potential_index(circuit, forecast_date, variant, now=None):
    now = now or clock.now()
    day0 = datetime.strptime(forecast_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    window_start = day0 - timedelta(hours=OBSERVATION_WINDOW_HOURS)
    window_end = day0 + timedelta(hours=OBSERVATION_WINDOW_HOURS)

    stations = [
        s
        for s in db.in_order(db.weather_stations.values())
        if s["circuit_id"] == circuit["id"] and s["telemetry_status"] in ("ONLINE", "DEGRADED")
    ]

    contributions = []
    for station in stations:
        observations = station_observations(station, window_start, window_end)
        if not observations:
            continue
        weight = D(station["representativeness_weight"])
        if station["telemetry_status"] == "DEGRADED":
            weight = weight * DEGRADED_WEIGHT_FACTOR
        if variant == "FORECAST":
            gust = max(D(o["wind_gust_mph"]) for o in observations)
            humidity = min(D(o["relative_humidity_pct"]) for o in observations)
            fuel = min(D(o["dead_fuel_moisture_pct"]) for o in observations)
        else:
            latest = max(
                observations, key=lambda o: (o["observed_at"], o["created_at"], o["_seq"])
            )
            gust = D(latest["wind_gust_mph"])
            humidity = D(latest["relative_humidity_pct"])
            fuel = D(latest["dead_fuel_moisture_pct"])
        contributions.append((weight, gust, humidity, fuel))

    if not contributions:
        raise ApiError(
            "ERR_OBSERVATION_WINDOW_EMPTY",
            "No weather observation falls inside the +/-24h window for this forecast date.",
        )

    total_weight = sum((c[0] for c in contributions), ZERO)
    gust = sum((c[0] * c[1] for c in contributions), ZERO) / total_weight
    humidity = sum((c[0] * c[2] for c in contributions), ZERO) / total_weight
    fuel = sum((c[0] * c[3] for c in contributions), ZERO) / total_weight

    if variant == "FORECAST":
        gust = rhu(gust, 1)
        humidity = rhu(humidity, 1)
        fuel = rhu(fuel, 1)

    wind_component = clamp((gust - WIND_THRESHOLD_MPH) * WIND_SLOPE, 0, 100)
    dryness_component = clamp(
        (Decimal("100") - humidity) + (DFM_REFERENCE_PCT - fuel) * DFM_SLOPE, 0, 100
    )
    terrain_component = TERRAIN_POINTS[circuit["hftd_tier"]]
    overdue = inspection_overdue(circuit, now)
    equipment_component = clamp(
        (Decimal("100") - D(circuit["equipment_condition_index"]))
        + (INSPECTION_OVERDUE_PENALTY if overdue else ZERO),
        0,
        100,
    )

    raw_score = (
        WIND_WEIGHT * wind_component
        + DRYNESS_WEIGHT * dryness_component
        + TERRAIN_WEIGHT * terrain_component
        + EQUIPMENT_WEIGHT * equipment_component
    )
    hardened = D(circuit["hardened_fraction"])
    score = rhu(raw_score * (ONE - HARDENING_CREDIT_FACTOR * hardened), 2)

    return {
        "contributing_station_count": len(contributions),
        "effective_wind_gust_mph": gust,
        "effective_relative_humidity_pct": humidity,
        "effective_dead_fuel_moisture_pct": fuel,
        "wind_component": wind_component,
        "dryness_component": dryness_component,
        "terrain_component": terrain_component,
        "equipment_component": equipment_component,
        "inspection_overdue": overdue,
        "hardened_fraction_applied": hardened,
        "fpi_score": score,
        "fpi_tier": fpi_tier(score),
    }


# ------------------------------------------------------------- C3 risk posture
def latest_forecast_index(circuit):
    rows = [
        i
        for i in db.fire_potential_indices.values()
        if i["circuit_id"] == circuit["id"] and i["computation_variant"] == "FORECAST"
    ]
    if not rows:
        return None
    return max(rows, key=lambda i: (i["forecast_date"], i["created_at"], i["_seq"]))


def recompute_risk_posture(circuit):
    index = latest_forecast_index(circuit)
    circuit["latest_forecast_fpi_score"] = index["fpi_score"] if index else None
    circuit["latest_forecast_fpi_tier"] = index["fpi_tier"] if index else None

    if circuit["energization_state"] in LOCKED_ENERGIZATION_STATES:
        circuit["risk_posture"] = "LOCKED"
        return circuit["risk_posture"]
    if index is None:
        circuit["risk_posture"] = "NORMAL"
    elif index["fpi_tier"] in ("R4", "R5"):
        circuit["risk_posture"] = "EXTREME"
    elif index["fpi_tier"] == "R3":
        circuit["risk_posture"] = "ELEVATED"
    else:
        circuit["risk_posture"] = "NORMAL"
    return circuit["risk_posture"]


# ------------------------------------------------------------------ C7 tiering
def customer_notification_tier(customer_class, medical_baseline):
    if customer_class == "CRITICAL_FACILITY":
        return "TIER_A_CRITICAL"
    if medical_baseline:
        return "TIER_B_MEDICAL"
    return "TIER_C_STANDARD"


# ------------------------------------------------------------ C11 mitigation
def risk_reduction_score(planned_miles, program_type, hftd_tier):
    return rhu(
        D(planned_miles) * PROGRAM_EFFECTIVENESS[program_type] * HFTD_RISK_MULTIPLIER[hftd_tier],
        2,
    )


def budget_cents(planned_miles, unit_cost_per_mile_cents):
    product = D(planned_miles) * D(unit_cost_per_mile_cents)
    return int(product.to_integral_value(rounding=ROUND_FLOOR)) if product >= 0 else int(product)


# ------------------------------------------------------------- C12/C13 filings
def compute_filing_metrics(plan_year):
    projects = [
        p
        for p in db.mitigation_projects.values()
        if p["plan_year"] == plan_year and p["status"] in QUALIFYING_FILING_STATUSES
    ]
    covered = ZERO
    underground = ZERO
    for project in projects:
        if project["program_type"] == "COVERED_CONDUCTOR":
            covered += D(project["completed_miles"])
        elif project["program_type"] == "UNDERGROUNDING":
            underground += D(project["completed_miles"])
    covered_reported = q(covered, 1)
    underground_reported = q(underground, 1)

    closed_events = [
        e
        for e in db.psps_events.values()
        if e["scope_status"] == "CLOSED"
        and e.get("actual_de_energized_at") is not None
        and e["actual_de_energized_at"].year == plan_year
    ]
    closed_events.sort(key=lambda e: (e["actual_de_energized_at"], e["created_at"], e["_seq"]))

    customer_minutes = 0
    for event in closed_events:
        scopes = db.in_order(
            [
                s
                for s in db.event_scopes.values()
                if s["psps_event_id"] == event["id"] and s["scope_status"] == "CONFIRMED"
            ]
        )
        for scope in scopes:
            if scope.get("restored_at") is None:
                continue
            minutes = floor_minutes(event["actual_de_energized_at"], scope["restored_at"])
            customer_minutes += int(scope["customer_count_snapshot"]) * minutes

    closed_ids = set(e["id"] for e in closed_events)
    lead_batches = [
        b
        for b in db.notification_batches.values()
        if b["psps_event_id"] in closed_ids
        and b["stage"] == "ADVANCE_48H"
        and b["status"] in ("DISPATCHED", "FAILED_PARTIAL")
    ]
    if lead_batches:
        total_lead = sum((D(b["lead_time_minutes"]) for b in lead_batches), ZERO)
        avg_lead = rhu(total_lead / Decimal(len(lead_batches)), 2)
    else:
        avg_lead = Decimal("0.00")

    metrics = {
        "qualifying_project_count": len(projects),
        "covered_conductor_miles_reported": covered_reported,
        "underground_miles_reported": underground_reported,
        "psps_event_count": len(closed_events),
        "customer_minutes_interrupted": customer_minutes,
        "avg_notification_lead_minutes": avg_lead,
    }
    metrics["compliance_score"] = compliance_score(
        underground_reported, covered_reported, avg_lead
    )
    return metrics


def compliance_score(underground_reported, covered_reported, avg_lead):
    underground_term = Decimal("40") * min(
        ONE, D(underground_reported) / UNDERGROUND_TARGET_MILES
    )
    covered_term = Decimal("30") * min(
        ONE, D(covered_reported) / COVERED_CONDUCTOR_TARGET_MILES
    )
    lead_term = Decimal("30") * min(ONE, D(avg_lead) / LEAD_TARGET_MINUTES)
    total = underground_term + covered_term + lead_term
    total = clamp(total, 0, 100)
    return rhu(total, 2)
