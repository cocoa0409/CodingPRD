"""Request-payload factories.

Each factory builds only the client-supplied fields the PRD declares for that
write; every derived, system and ledger field is left to the server.  Optional
fields are omitted from the body unless a caller supplies them, so the defaults
of PRD §3 are exercised by default.  `**overrides` merges extra or replacement
keys, and `without()` drops keys so a test can probe a missing required field.
"""

from .constants import CLOCK_STARTUP  # noqa: F401  (re-exported for convenience)
from .types import (
    AreaType,
    LicenseCategory,
    PlanTaskType,
    PlayEventType,
    SoilType,
    SourceType,
    UnitType,
    WeatherEventType,
    WindowTaskType,
)


def without(payload, *keys):
    """A copy of `payload` with the named keys removed."""
    return {k: v for k, v in payload.items() if k not in keys}


def _compact(payload, optional):
    """Merge only those optional entries the caller actually supplied."""
    payload.update({k: v for k, v in optional.items() if v is not None})
    return payload


# --------------------------------------------------------------------------
# Courses (PRD §3.1)
# --------------------------------------------------------------------------
def course_payload(
    name="Cedar Ridge GC",
    region_code="OR",
    annual_water_allocation_gal=100000,
    water_restricted_threshold_pct=None,
    water_suspended_threshold_pct=None,
    **overrides,
):
    payload = {
        "name": name,
        "region_code": region_code,
        "annual_water_allocation_gal": annual_water_allocation_gal,
    }
    _compact(
        payload,
        {
            "water_restricted_threshold_pct": water_restricted_threshold_pct,
            "water_suspended_threshold_pct": water_suspended_threshold_pct,
        },
    )
    payload.update(overrides)
    return payload


def water_allocation_payload(
    annual_water_allocation_gal=None,
    water_restricted_threshold_pct=None,
    water_suspended_threshold_pct=None,
    **overrides,
):
    payload = {}
    _compact(
        payload,
        {
            "annual_water_allocation_gal": annual_water_allocation_gal,
            "water_restricted_threshold_pct": water_restricted_threshold_pct,
            "water_suspended_threshold_pct": water_suspended_threshold_pct,
        },
    )
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Turf areas (PRD §3.2)
# --------------------------------------------------------------------------
def turf_area_payload(
    course_id,
    area_type=AreaType.GREEN.value,
    hole_number=7,
    area_sq_ft=5500,
    mowing_height_mm=3.2,
    distance_to_water_ft=40,
    soil_type=SoilType.SAND_USGA.value,
    target_moisture_pct=None,
    **overrides,
):
    payload = {
        "course_id": course_id,
        "area_type": area_type,
        "hole_number": hole_number,
        "area_sq_ft": area_sq_ft,
        "mowing_height_mm": mowing_height_mm,
        "distance_to_water_ft": distance_to_water_ft,
        "soil_type": soil_type,
    }
    _compact(payload, {"target_moisture_pct": target_moisture_pct})
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Agronomic plans and their tasks (PRD §3.3)
# --------------------------------------------------------------------------
def plan_payload(course_id, plan_year=2026, nitrogen_budget_lb=40.00, **overrides):
    payload = {
        "course_id": course_id,
        "plan_year": plan_year,
        "nitrogen_budget_lb": nitrogen_budget_lb,
    }
    payload.update(overrides)
    return payload


def plan_task_payload(
    plan_id,
    turf_area_id,
    task_type=PlanTaskType.FERTILITY.value,
    nitrogen_lb_per_1000=None,
    planned_window_start="2026-08-10T00:00:00Z",
    planned_window_end="2026-08-20T00:00:00Z",
    **overrides,
):
    payload = {
        "plan_id": plan_id,
        "turf_area_id": turf_area_id,
        "task_type": task_type,
        "planned_window_start": planned_window_start,
        "planned_window_end": planned_window_end,
    }
    _compact(payload, {"nitrogen_lb_per_1000": nitrogen_lb_per_1000})
    payload.update(overrides)
    return payload


def approve_plan_payload(expected_plan_version, **overrides):
    payload = {"expected_plan_version": expected_plan_version}
    payload.update(overrides)
    return payload


def return_plan_payload(return_note=None, **overrides):
    payload = {}
    _compact(payload, {"return_note": return_note})
    payload.update(overrides)
    return payload


def schedule_task_payload(maintenance_window_id, expected_plan_version, **overrides):
    payload = {
        "maintenance_window_id": maintenance_window_id,
        "expected_plan_version": expected_plan_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Applicators and product labels (PRD §3.4)
# --------------------------------------------------------------------------
def applicator_payload(
    full_name="Dana Reyes",
    license_number="OR-CAT3-11001",
    license_category=LicenseCategory.CAT_3_TURF.value,
    license_expires_on="2027-06-30",
    **overrides,
):
    payload = {
        "full_name": full_name,
        "license_number": license_number,
        "license_category": license_category,
        "license_expires_on": license_expires_on,
    }
    payload.update(overrides)
    return payload


def product_payload(
    trade_name="Urea 46-0-0",
    epa_reg_no="NA-FERT-0001",
    requires_license_category=LicenseCategory.CAT_3_TURF.value,
    rei_hours=0,
    min_buffer_ft=0,
    max_wind_speed_mph=15,
    posting_required=False,
    nitrogen_pct=46,
    **overrides,
):
    payload = {
        "trade_name": trade_name,
        "epa_reg_no": epa_reg_no,
        "requires_license_category": requires_license_category,
        "rei_hours": rei_hours,
        "min_buffer_ft": min_buffer_ft,
        "max_wind_speed_mph": max_wind_speed_mph,
        "posting_required": posting_required,
        "nitrogen_pct": nitrogen_pct,
    }
    payload.update(overrides)
    return payload


def application_payload(
    turf_area_id,
    product_id,
    applicator_id,
    applied_at,
    rate_lb_per_acre=200,
    wind_speed_mph=5,
    distance_to_water_ft=40,
    plan_task_id=None,
    **overrides,
):
    payload = {
        "turf_area_id": turf_area_id,
        "product_id": product_id,
        "applicator_id": applicator_id,
        "applied_at": applied_at,
        "rate_lb_per_acre": rate_lb_per_acre,
        "wind_speed_mph": wind_speed_mph,
        "distance_to_water_ft": distance_to_water_ft,
    }
    _compact(payload, {"plan_task_id": plan_task_id})
    payload.update(overrides)
    return payload


def void_payload(void_reason, **overrides):
    payload = {"void_reason": void_reason}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Irrigation (PRD §3.5)
# --------------------------------------------------------------------------
def pump_station_payload(
    course_id,
    source_type=SourceType.WELL.value,
    max_flow_gpm=300,
    max_concurrent_zones=2,
    daily_withdrawal_cap_gal=10000,
    **overrides,
):
    payload = {
        "course_id": course_id,
        "source_type": source_type,
        "max_flow_gpm": max_flow_gpm,
        "max_concurrent_zones": max_concurrent_zones,
        "daily_withdrawal_cap_gal": daily_withdrawal_cap_gal,
    }
    payload.update(overrides)
    return payload


def irrigation_run_payload(
    pump_station_id,
    turf_area_id,
    window_start,
    window_end,
    target_moisture_deficit_pct,
    expected_pump_station_version,
    **overrides,
):
    payload = {
        "pump_station_id": pump_station_id,
        "turf_area_id": turf_area_id,
        "window_start": window_start,
        "window_end": window_end,
        "target_moisture_deficit_pct": target_moisture_deficit_pct,
        "expected_pump_station_version": expected_pump_station_version,
    }
    payload.update(overrides)
    return payload


def complete_run_payload(actual_minutes=None, **overrides):
    payload = {}
    _compact(payload, {"actual_minutes": actual_minutes})
    payload.update(overrides)
    return payload


def reverse_run_payload(reversal_note=None, **overrides):
    payload = {}
    _compact(payload, {"reversal_note": reversal_note})
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Crew windows (PRD §3.6)
# --------------------------------------------------------------------------
def maintenance_window_payload(
    course_id,
    turf_area_id,
    task_type,
    window_start,
    window_end,
    crew_size=3,
    required_unit_type=None,
    **overrides,
):
    payload = {
        "course_id": course_id,
        "turf_area_id": turf_area_id,
        "task_type": task_type,
        "window_start": window_start,
        "window_end": window_end,
        "crew_size": crew_size,
    }
    _compact(payload, {"required_unit_type": required_unit_type})
    payload.update(overrides)
    return payload


def reschedule_window_payload(window_start, window_end, crew_size=None, **overrides):
    payload = {"window_start": window_start, "window_end": window_end}
    _compact(payload, {"crew_size": crew_size})
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Play events and readings (PRD §3.7)
# --------------------------------------------------------------------------
def play_event_payload(
    course_id,
    event_type=PlayEventType.STANDARD_TEE_TIMES.value,
    start_at="2026-08-05T14:00:00Z",
    end_at="2026-08-05T19:00:00Z",
    holes_in_play=18,
    field_size=80,
    **overrides,
):
    payload = {
        "course_id": course_id,
        "event_type": event_type,
        "start_at": start_at,
        "end_at": end_at,
        "holes_in_play": holes_in_play,
        "field_size": field_size,
    }
    payload.update(overrides)
    return payload


def playability_reading_payload(
    turf_area_id,
    measured_at,
    green_speed_ft=11.0,
    firmness_gravities=1.35,
    moisture_pct=18.0,
    **overrides,
):
    payload = {
        "turf_area_id": turf_area_id,
        "measured_at": measured_at,
        "green_speed_ft": green_speed_ft,
        "firmness_gravities": firmness_gravities,
        "moisture_pct": moisture_pct,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# The fleet (PRD §3.8)
# --------------------------------------------------------------------------
def equipment_unit_payload(
    course_id,
    unit_type=UnitType.TRIPLEX_GREENS_MOWER.value,
    model_year=2018,
    purchase_cost=38000,
    expected_life_hours=6000,
    service_interval_hours=250,
    avg_daily_hours=3.5,
    initial_engine_hours=None,
    **overrides,
):
    payload = {
        "course_id": course_id,
        "unit_type": unit_type,
        "model_year": model_year,
        "purchase_cost": purchase_cost,
        "expected_life_hours": expected_life_hours,
        "service_interval_hours": service_interval_hours,
        "avg_daily_hours": avg_daily_hours,
    }
    _compact(payload, {"initial_engine_hours": initial_engine_hours})
    payload.update(overrides)
    return payload


def service_payload(service_note=None, **overrides):
    payload = {}
    _compact(payload, {"service_note": service_note})
    payload.update(overrides)
    return payload


def retire_payload(replacement_unit_id=None, **overrides):
    payload = {}
    _compact(payload, {"replacement_unit_id": replacement_unit_id})
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Weather (PRD §3.9)
# --------------------------------------------------------------------------
def weather_event_payload(
    course_id,
    event_type,
    expected_clear_at,
    expected_course_version,
    delay_minutes=None,
    affected_turf_area_ids=None,
    **overrides,
):
    payload = {
        "course_id": course_id,
        "event_type": event_type,
        "expected_clear_at": expected_clear_at,
        "expected_course_version": expected_course_version,
    }
    _compact(
        payload,
        {
            "delay_minutes": delay_minutes,
            "affected_turf_area_ids": affected_turf_area_ids,
        },
    )
    payload.update(overrides)
    return payload


def frost_payload(
    course_id, delay_minutes, expected_clear_at, expected_course_version, **overrides
):
    return weather_event_payload(
        course_id,
        WeatherEventType.FROST.value,
        expected_clear_at,
        expected_course_version,
        delay_minutes=delay_minutes,
        **overrides,
    )


def storm_damage_payload(
    course_id,
    affected_turf_area_ids,
    expected_clear_at,
    expected_course_version,
    **overrides,
):
    return weather_event_payload(
        course_id,
        WeatherEventType.STORM_DAMAGE.value,
        expected_clear_at,
        expected_course_version,
        affected_turf_area_ids=affected_turf_area_ids,
        **overrides,
    )


# Handy aliases so a test reads in the vocabulary of the domain.
FERTILITY = PlanTaskType.FERTILITY.value
AERATION = PlanTaskType.AERATION.value
TOPDRESSING = PlanTaskType.TOPDRESSING.value
PEST_CONTROL = PlanTaskType.PEST_CONTROL.value
MOWING = WindowTaskType.MOWING.value
STORM_CLEANUP = WindowTaskType.STORM_CLEANUP.value
