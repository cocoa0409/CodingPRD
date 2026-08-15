"""Payload factories — one per creatable resource, input fields only.

Defaults line up with the shared fixture clock: event start 2026-10-15T08:00:00Z,
closure window 06:00-12:00, wave band 18-39.
"""
from .constants import DEFAULT_ENTRY_FEE_CENTS, DEFAULT_WATER_POOL_UNITS, EVENT_START_ISO


def create_event_payload(**overrides) -> dict:
    defaults = {
        "name": "Tri A",
        "start_date": EVENT_START_ISO,
        "has_swim": False,
        "water_pool_units": DEFAULT_WATER_POOL_UNITS,
    }
    defaults.update(overrides)
    return defaults


def create_road_segment_payload(**overrides) -> dict:
    defaults = {
        "name": "Main St",
        "length_km": 5.0,
        "closure_start": "2026-10-15T06:00:00Z",
        "closure_end": "2026-10-15T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "authority_name": "City PD",
        "requested_start": "2026-10-15T06:00:00Z",
        "requested_end": "2026-10-15T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_wave_payload(**overrides) -> dict:
    defaults = {
        "label": "W1",
        "division": "AGE_GROUP",
        "scheduled_start_time": EVENT_START_ISO,
        "capacity": 2,
        "draft_legal": False,
        "age_band_min": 18,
        "age_band_max": 39,
    }
    defaults.update(overrides)
    return defaults


def create_athlete_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ann A",
        "birth_date": "1990-01-01",
        "license_number": "USAT-1",
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(**overrides) -> dict:
    defaults = {
        "athlete_id": "",  # required — caller must supply
        "division": "AGE_GROUP",
        "entry_fee_cents": DEFAULT_ENTRY_FEE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_aid_station_payload(**overrides) -> dict:
    defaults = {
        "name": "AS-1",
        "location_km": 10.0,
        "required_volunteers": 1,
        "required_water_units": 100,
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_assignment_payload(**overrides) -> dict:
    defaults = {
        "volunteer_id": "vol-1",
        "shift_start": "2026-10-15T06:00:00Z",
        "shift_end": "2026-10-15T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_safety_assessment_payload(**overrides) -> dict:
    defaults = {
        "water_temp_celsius": 20.0,
        "lightning_within_10km": False,
    }
    defaults.update(overrides)
    return defaults


def create_timing_record_payload(**overrides) -> dict:
    defaults = {
        "discipline": "SWIM",
        "recorded_at": "2026-10-15T08:15:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_penalty_payload(**overrides) -> dict:
    defaults = {
        "kind": "DRAFTING",
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {
        "grounds": "appeal grounds",
    }
    defaults.update(overrides)
    return defaults


def create_result_correction_payload(**overrides) -> dict:
    defaults = {
        "expected_result_version": 1,
        "discipline": "BIKE",
        "corrected_seconds": 3500,
    }
    defaults.update(overrides)
    return defaults


def create_penalty_amend_payload(**overrides) -> dict:
    defaults = {
        "expected_penalty_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_decision_payload(**overrides) -> dict:
    defaults = {
        "decision": "UPHELD",
    }
    defaults.update(overrides)
    return defaults
