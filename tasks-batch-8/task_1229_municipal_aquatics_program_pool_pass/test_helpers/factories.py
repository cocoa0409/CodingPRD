"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

_counter = itertools.count(1)

DEFAULTS = {
    "FACILITY_NAME": "Community Pool",
    "FACILITY_ADDRESS": "100 Recreation Way",
    "MAX_BATHER_CAPACITY": 100,
    "LAP_LANE_COUNT": 4,
    "SEASON_NAME": "Summer 2026",
    "SEASON_START": "2026-06-01T00:00:00Z",
    "SEASON_END": "2026-08-31T00:00:00Z",
    "RESIDENT_PASS_PRICE_CENTS": 10000,
    "NON_RESIDENT_PASS_PRICE_CENTS": 15000,
    "RESIDENT_DAILY_PRICE_CENTS": 500,
    "NON_RESIDENT_DAILY_PRICE_CENTS": 800,
    "HOLDER_DOB_ADULT": "1990-01-01T00:00:00Z",
    "CERT_EXPIRES": "2027-01-01T00:00:00Z",
    "HIRED_ON": "2026-01-01T00:00:00Z",
}


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq(DEFAULTS["FACILITY_NAME"]),
        "address": DEFAULTS["FACILITY_ADDRESS"],
        "max_bather_capacity": DEFAULTS["MAX_BATHER_CAPACITY"],
        "lap_lane_count": DEFAULTS["LAP_LANE_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_season_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "season_name": DEFAULTS["SEASON_NAME"],
        "start_date": DEFAULTS["SEASON_START"],
        "end_date": DEFAULTS["SEASON_END"],
        "resident_pass_price_cents": DEFAULTS["RESIDENT_PASS_PRICE_CENTS"],
        "non_resident_pass_price_cents": DEFAULTS["NON_RESIDENT_PASS_PRICE_CENTS"],
        "resident_daily_price_cents": DEFAULTS["RESIDENT_DAILY_PRICE_CENTS"],
        "non_resident_daily_price_cents": DEFAULTS["NON_RESIDENT_DAILY_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_pass_holder_payload(**overrides) -> dict:
    defaults = {
        "full_name": _uniq("Patron"),
        "date_of_birth": DEFAULTS["HOLDER_DOB_ADULT"],
        "residency_status": "RESIDENT",
        "email": f"{_uniq('patron')}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_pass_payload(pass_holder_id, season_id, **overrides) -> dict:
    defaults = {"pass_holder_id": pass_holder_id, "season_id": season_id}
    defaults.update(overrides)
    return defaults


def create_admission_payload(facility_id, pass_holder_id, admission_date,
                             **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "pass_holder_id": pass_holder_id,
        "admission_date": admission_date,
    }
    defaults.update(overrides)
    return defaults


def create_lesson_level_payload(**overrides) -> dict:
    defaults = {
        "level_code": _uniq("L"),
        "display_name": "Water Acclimation",
        "min_age_years": 5,
        "capacity_per_session": 10,
    }
    defaults.update(overrides)
    return defaults


def create_lesson_session_payload(facility_id, level_id, season_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "level_id": level_id,
        "season_id": season_id,
        "start_datetime": "2026-07-01T09:00:00Z",
        "end_datetime": "2026-07-31T10:00:00Z",
        "lanes_required": 1,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(lesson_session_id, pass_holder_id, **overrides) -> dict:
    defaults = {
        "lesson_session_id": lesson_session_id,
        "pass_holder_id": pass_holder_id,
    }
    defaults.update(overrides)
    return defaults


def create_lifeguard_payload(**overrides) -> dict:
    defaults = {
        "full_name": _uniq("Guard"),
        "certification_id": _uniq("RC"),
        "cert_expires_on": DEFAULTS["CERT_EXPIRES"],
        "hired_on": DEFAULTS["HIRED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(facility_id, lifeguard_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "lifeguard_id": lifeguard_id,
        "shift_start": "2026-07-01T10:00:00Z",
        "shift_end": "2026-07-01T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_chemistry_log_payload(recorded_by_lifeguard_id, **overrides) -> dict:
    defaults = {
        "recorded_at": "2026-06-15T10:00:00Z",
        "free_chlorine_ppm": 2.5,
        "ph": 7.5,
        "combined_chlorine_ppm": 0.2,
        "recorded_by_lifeguard_id": recorded_by_lifeguard_id,
    }
    defaults.update(overrides)
    return defaults


def create_lane_allocation_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "purpose": "SWIM_TEAM",
        "start_datetime": "2026-07-15T09:00:00Z",
        "end_datetime": "2026-07-15T11:00:00Z",
        "lane_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(facility_id, pass_holder_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "pass_holder_id": pass_holder_id,
        "party_size": 10,
        "start_datetime": "2026-08-01T14:00:00Z",
        "end_datetime": "2026-08-01T16:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_incident_report_payload(facility_id, reporting_lifeguard_id,
                                   involved_pass_holder_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "reporting_lifeguard_id": reporting_lifeguard_id,
        "involved_pass_holder_id": involved_pass_holder_id,
        "incident_type": "RULE_VIOLATION",
        "occurred_at": "2026-06-15T11:00:00Z",
        "severity": "MINOR",
        "narrative": "Incident narrative",
    }
    defaults.update(overrides)
    return defaults


def create_closure_payload(**overrides) -> dict:
    defaults = {
        "closure_reason": "WEATHER",
        "started_at": "2026-07-20T10:30:00Z",
    }
    defaults.update(overrides)
    return defaults
