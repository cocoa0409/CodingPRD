"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import (
    HARVESTED_AT,
    SEASON_ENDS_AT,
    SEASON_NAME,
    SEASON_STARTS_AT,
    SIGNUP_CLOSES_AT,
    SIGNUP_OPENS_AT,
    SLOT_ENDS_AT,
    SLOT_STARTS_AT,
    TEST_DEFAULTS,
)

_counter = {"n": 0}


def _uniq(tag: str) -> str:
    _counter["n"] += 1
    return f"{tag}-{_counter['n']}"


def create_volunteer_payload(**overrides) -> dict:
    n = _uniq("vol")
    defaults = {
        "full_name": f"Vol {n}",
        "email": f"{n}@example.org",
        "date_of_birth": TEST_DEFAULTS["ADULT_DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "volunteer_id": None,
        "cert_type": "SUPERVISION",
        "expires_at": TEST_DEFAULTS["CERT_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": SEASON_NAME,
        "signup_opens_at": SIGNUP_OPENS_AT,
        "signup_closes_at": SIGNUP_CLOSES_AT,
        "season_starts_at": SEASON_STARTS_AT,
        "season_ends_at": SEASON_ENDS_AT,
        "water_budget_gallons": TEST_DEFAULTS.get("WATER_BUDGET", 1000),
    }
    defaults.update(overrides)
    return defaults


def create_bed_payload(**overrides) -> dict:
    defaults = {
        "bed_code": _uniq("B"),
        "size_sq_ft": TEST_DEFAULTS["BED_SIZE"],
        "sun_exposure": "FULL",
        "irrigation_zone": TEST_DEFAULTS["BED_ZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_crop_plan_payload(**overrides) -> dict:
    defaults = {
        "season_id": None,
        "bed_id": None,
        "proposer_volunteer_id": None,
        "crop_type": TEST_DEFAULTS["CROP_TYPE"],
        "plant_family": TEST_DEFAULTS["PLANT_FAMILY"],
        "requested_sq_ft": TEST_DEFAULTS["PLAN_SQ_FT"],
        "planned_start_date": TEST_DEFAULTS["PLAN_START"],
        "planned_end_date": TEST_DEFAULTS["PLAN_END"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_slot_payload(**overrides) -> dict:
    defaults = {
        "season_id": None,
        "task_type": TEST_DEFAULTS["TASK_TYPE"],
        "starts_at": SLOT_STARTS_AT,
        "ends_at": SLOT_ENDS_AT,
        "capacity_total": 3,
        "capacity_youth": 1,
    }
    defaults.update(overrides)
    return defaults


def create_shift_signup_payload(**overrides) -> dict:
    defaults = {
        "slot_id": None,
        "volunteer_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_group_booking_payload(**overrides) -> dict:
    defaults = {
        "slot_id": None,
        "leader_volunteer_id": None,
        "organization_name": _uniq("Org"),
        "member_count": 10,
        "minor_count": 0,
        "chaperone_count": 0,
        "chaperone_volunteer_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_shed_key_payload(**overrides) -> dict:
    defaults = {"key_code": _uniq("K")}
    defaults.update(overrides)
    return defaults


def create_tool_payload(**overrides) -> dict:
    defaults = {
        "tool_name": _uniq("Tool"),
        "category": "HAND",
        "total_count": 5,
    }
    defaults.update(overrides)
    return defaults


def create_tool_checkout_payload(**overrides) -> dict:
    defaults = {
        "tool_id": None,
        "volunteer_id": None,
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_harvest_log_payload(**overrides) -> dict:
    defaults = {
        "season_id": None,
        "bed_id": None,
        "logged_by_volunteer_id": None,
        "crop_type": TEST_DEFAULTS["CROP_TYPE"],
        "weight_grams": 10000,
        "quality_grade": "A",
        "harvested_at": HARVESTED_AT,
        "safety_attestation": True,
    }
    defaults.update(overrides)
    return defaults


def create_donation_recipient_payload(**overrides) -> dict:
    n = _uniq("org")
    defaults = {
        "org_name": f"Recipient {n}",
        "contact_email": f"{n}@example.org",
        "weekly_capacity_grams": TEST_DEFAULTS["RECIPIENT_CAPACITY"],
        "priority_tier": 1,
    }
    defaults.update(overrides)
    return defaults


def create_donation_allocation_payload(**overrides) -> dict:
    defaults = {
        "harvest_log_id": None,
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_irrigation_schedule_payload(**overrides) -> dict:
    defaults = {
        "season_id": None,
        "zone": "Z1",
        "planned_start_at": "2026-08-20T10:00:00Z",
        "planned_end_at": "2026-08-20T11:00:00Z",
        "planned_gallons": 100,
        "expected_season_version": None,
    }
    defaults.update(overrides)
    return defaults
