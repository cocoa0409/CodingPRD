"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_CLOSING_DATE,
    DEFAULT_OPENING_DATE,
    TEST_DEFAULTS,
)


def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Revel",
        "opening_date": DEFAULT_OPENING_DATE,
        "closing_date": DEFAULT_CLOSING_DATE,
        "daily_capacity": TEST_DEFAULTS["DAILY_CAPACITY"],
        "group_min_size": TEST_DEFAULTS["GROUP_MIN_SIZE"],
        "volunteer_min_hours": TEST_DEFAULTS["VOLUNTEER_MIN_HOURS"],
        "weather_call_deadline_hour": TEST_DEFAULTS["WEATHER_CALL_DEADLINE_HOUR"],
        "rain_check_grace_days": TEST_DEFAULTS["RAIN_CHECK_GRACE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_faire_day_payload(season_id: str, date: str = DEFAULT_OPENING_DATE, **overrides) -> dict:
    defaults = {"season_id": season_id, "date": date}
    defaults.update(overrides)
    return defaults


def create_performer_payload(**overrides) -> dict:
    defaults = {
        "stage_name": "Test Trouper",
        "act_type": "MUSIC",
        "base_day_rate_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_cast_contract_payload(season_id: str, performer_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "performer_id": performer_id,
        "offered_day_rate_cents": 20000,
        "guaranteed_days": 2,
        "weather_pay_pct": 0.5,
        "required_rehearsal_hours": 2,
    }
    defaults.update(overrides)
    return defaults


def create_rehearsal_slot_payload(
    contract_id: str,
    stage_name: str = "MAIN",
    start_time: str = "2026-05-10T09:00:00Z",
    end_time: str = "2026-05-10T10:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "contract_id": contract_id,
        "stage_name": stage_name,
        "start_time": start_time,
        "end_time": end_time,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {"business_name": "Test Vendor", "category": "ARTISAN"}
    defaults.update(overrides)
    return defaults


def create_vendor_application_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "booth_size_sqft": 64,
        "requested_location_tier": "MEADOW",
    }
    defaults.update(overrides)
    return defaults


def decide_application_payload(outcome: str, **overrides) -> dict:
    defaults = {
        "craft_score": 8,
        "authenticity_score": 8,
        "safety_score": 8,
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


def create_booth_assignment_payload(
    application_id: str,
    booth_site: str = "A-01",
    residency_start_date: str = "2026-06-06T00:00:00Z",
    residency_end_date: str = "2026-06-20T00:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "application_id": application_id,
        "booth_site": booth_site,
        "residency_start_date": residency_start_date,
        "residency_end_date": residency_end_date,
    }
    defaults.update(overrides)
    return defaults


def create_food_permit_payload(application_id: str, **overrides) -> dict:
    defaults = {"application_id": application_id}
    defaults.update(overrides)
    return defaults


def create_ticket_order_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "order_type": "DAY",
        "quantity": 1,
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_shift_payload(
    season_id: str,
    faire_day_id: str,
    **overrides,
) -> dict:
    defaults = {
        "season_id": season_id,
        "faire_day_id": faire_day_id,
        "role": "GATE",
        "start_time": "2026-06-06T08:00:00Z",
        "end_time": "2026-06-06T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_conduct_case_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "category": "BEHAVIOR",
        "subject_description": "Test conduct violation",
    }
    defaults.update(overrides)
    return defaults


def create_build_task_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "phase": "BUILD",
        "name": "Test task",
    }
    defaults.update(overrides)
    return defaults
