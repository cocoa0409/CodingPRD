"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import (
    BURN_DAY,
    BURN_DAY_TS,
    CHECKLIST_ITEMS,
    PLAN_WINDOW_END,
    PLAN_WINDOW_START,
    PRESCRIPTION_DEFAULTS,
    WEATHER_IN_PRESCRIPTION,
)

DEFAULTS = {
    "ASSOC_NAME": "Assoc",
    "AIRSHED_CAP": 500,
    "SINGLE_CLAIM_CAP": 500_000,
    "LANDOWNER_CAP": 1_000_000,
    "INITIAL_FUND": 10_000_000,
    "LANDOWNER_NAME": "Lo",
    "LANDOWNER_EMAIL": "lo@x.com",
    "BOSS_NAME": "Boss A",
    "REVIEWER_NAME": "Boss R",
    "TIER": "RXB3",
    "CONTRACTOR_NAME": "EngCo",
    "RESOURCE_TYPE": "ENGINE",
    "CAPACITY": 4,
    "PERSONNEL": 5,
    "DAY_RATE": 100_000,
    "PARCEL_NAME": "P1",
    "ACREAGE": 120,
    "FUEL_MODEL": "BRUSH",
    "SLOPE_CLASS": "MODERATE",
    "AIRSHED": "ASH-1",
    "DROUGHT": 10,
    "PLANNED_ACRES": 100,
}


def create_association_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ASSOC_NAME"],
        "airshed_daily_acres_cap": DEFAULTS["AIRSHED_CAP"],
        "single_claim_cap_cents": DEFAULTS["SINGLE_CLAIM_CAP"],
        "landowner_liability_cap_cents": DEFAULTS["LANDOWNER_CAP"],
        "initial_fund_cents": DEFAULTS["INITIAL_FUND"],
    }
    defaults.update(overrides)
    return defaults


def create_landowner_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LANDOWNER_NAME"],
        "contact_email": DEFAULTS["LANDOWNER_EMAIL"],
        "liability_waiver_signed": True,
    }
    defaults.update(overrides)
    return defaults


def create_burn_boss_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BOSS_NAME"],
        "certification_tier": DEFAULTS["TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CONTRACTOR_NAME"],
        "resource_type": DEFAULTS["RESOURCE_TYPE"],
        "capacity_units": DEFAULTS["CAPACITY"],
        "personnel_per_unit": DEFAULTS["PERSONNEL"],
        "day_rate_cents_per_unit": DEFAULTS["DAY_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_parcel_payload(landowner_id: str, **overrides) -> dict:
    defaults = {
        "landowner_id": landowner_id,
        "name": DEFAULTS["PARCEL_NAME"],
        "acreage": DEFAULTS["ACREAGE"],
        "fuel_model": DEFAULTS["FUEL_MODEL"],
        "slope_class": DEFAULTS["SLOPE_CLASS"],
        "wui_adjacent": False,
        "airshed_id": DEFAULTS["AIRSHED"],
        "drought_index": DEFAULTS["DROUGHT"],
    }
    defaults.update(overrides)
    return defaults


def default_treatment_lines(acres: int = DEFAULTS["PLANNED_ACRES"],
                            category: str = "BROADCAST",
                            rate_class: str = "GRASS") -> list:
    return [{"category": category, "rate_class": rate_class, "acres": acres}]


def create_burn_plan_payload(parcel_id: str, expected_parcel_version: int, **overrides) -> dict:
    defaults = {
        "parcel_id": parcel_id,
        "expected_parcel_version": expected_parcel_version,
        "planned_acres": DEFAULTS["PLANNED_ACRES"],
        "planned_window_start": PLAN_WINDOW_START,
        "planned_window_end": PLAN_WINDOW_END,
        **PRESCRIPTION_DEFAULTS,
        "treatment_lines": default_treatment_lines(DEFAULTS["PLANNED_ACRES"]),
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {"notifications_required": 1}
    defaults.update(overrides)
    return defaults


def create_notification_payload(**overrides) -> dict:
    defaults = {"recipient_name": "N1", "channel": "MAIL"}
    defaults.update(overrides)
    return defaults


def create_smoke_approval_payload(**overrides) -> dict:
    defaults = {"requested_burn_date": BURN_DAY, "requested_acres": DEFAULTS["PLANNED_ACRES"]}
    defaults.update(overrides)
    return defaults


def create_contingency_plan_payload(**overrides) -> dict:
    defaults = {
        "escape_trigger_points": "flame>4ft",
        "min_holding_personnel": 10,
        "water_supply_description": "tender onsite",
        "evacuation_route_description": "Hwy 9",
    }
    defaults.update(overrides)
    return defaults


def create_ignition_plan_payload(expected_burn_plan_version: int, **overrides) -> dict:
    defaults = {
        "expected_burn_plan_version": expected_burn_plan_version,
        "ignition_method": "DRIP_TORCH",
        "test_fire_required": True,
        "steps": [{"step_index": 1, "zone_label": "north", "technique": "strip"}],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(contractor_id: str, **overrides) -> dict:
    defaults = {
        "contractor_id": contractor_id,
        "units": 1,
        "window_start": BURN_DAY,
        "window_end": "2026-05-13",
    }
    defaults.update(overrides)
    return defaults


def create_execution_payload(**overrides) -> dict:
    defaults = {"scheduled_date": BURN_DAY}
    defaults.update(overrides)
    return defaults


def create_weather_observation_payload(**overrides) -> dict:
    defaults = {"observed_at": BURN_DAY_TS, **WEATHER_IN_PRESCRIPTION}
    defaults.update(overrides)
    return defaults


def go_no_go_payload(results: dict = None, items: list = None) -> dict:
    """All six items PASS by default; `results` maps item -> PASS|FAIL overrides,
    `items` replaces the item list entirely (for incomplete-checklist probes)."""
    if items is not None:
        answers = [{"item": i, "result": "PASS"} for i in items]
    else:
        results = results or {}
        answers = [
            {"item": item, "result": results.get(item, "PASS")}
            for item in CHECKLIST_ITEMS
        ]
    return {"checklist_answers": answers}


def create_incident_payload(**overrides) -> dict:
    defaults = {"incident_type": "SPOT"}
    defaults.update(overrides)
    return defaults


def assess_costs_payload(**overrides) -> dict:
    defaults = {"suppression_cost_cents": 3_000_000, "escaped_acres": 60}
    defaults.update(overrides)
    return defaults


def create_cost_share_payload(landowner_id: str, burn_plan_id: str, **overrides) -> dict:
    defaults = {
        "landowner_id": landowner_id,
        "burn_plan_id": burn_plan_id,
        "funding_tier": "STANDARD",
        "treatment_lines": default_treatment_lines(DEFAULTS["PLANNED_ACRES"]),
    }
    defaults.update(overrides)
    return defaults


def submit_report_payload(lines: list) -> dict:
    return {"actual_treatment_lines": lines}


def adjudicate_payload(outcome: str, negligence_found: bool) -> dict:
    return {"outcome": outcome, "negligence_found": negligence_found}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def close_execution_payload(lines: list) -> dict:
    return {"actual_treatment_lines": lines}


def reject_reason_payload(reason: str = "insufficient detail") -> dict:
    return {"reason": reason}
