"""Payload factories — one per creatable entity, input fields only.

Defaults target the canonical race day (2026-08-01) used across the suite.
"""
from .constants import TEST_DEFAULTS


def create_race_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Race 10K",
        "race_date": TEST_DEFAULTS["RACE_DATE"],
        "distance_km": 10.0,
        "course_type": "CERTIFIED_COURSE",
        "course_time_limit_minutes": 120,
    }
    defaults.update(overrides)
    return defaults


def create_wave_payload(race_id, wave_index, scheduled_start_time, max_capacity,
                        **overrides) -> dict:
    defaults = {
        "race_id": race_id,
        "wave_index": wave_index,
        "scheduled_start_time": scheduled_start_time,
        "max_capacity": max_capacity,
    }
    defaults.update(overrides)
    return defaults


def create_timing_point_payload(race_id, point_index, kind, distance_km, device_id,
                                deploy_at=None, expected_teardown_at=None,
                                **overrides) -> dict:
    defaults = {
        "race_id": race_id,
        "point_index": point_index,
        "kind": kind,
        "distance_km": distance_km,
        "device_id": device_id,
        "deploy_at": deploy_at or TEST_DEFAULTS["DEPLOY_AT"],
        "expected_teardown_at": expected_teardown_at or TEST_DEFAULTS["TEARDOWN_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(race_id, wave_id, bib_number, participant_name,
                                birth_date, gender, **overrides) -> dict:
    defaults = {
        "race_id": race_id,
        "wave_id": wave_id,
        "bib_number": bib_number,
        "participant_name": participant_name,
        "birth_date": birth_date,
        "gender": gender,
    }
    defaults.update(overrides)
    return defaults


def create_chip_payload(chip_code, **overrides) -> dict:
    defaults = {"chip_code": chip_code}
    defaults.update(overrides)
    return defaults


def create_timing_read_payload(timing_point_id, chip_id, read_timestamp,
                               **overrides) -> dict:
    defaults = {
        "timing_point_id": timing_point_id,
        "chip_id": chip_id,
        "read_timestamp": read_timestamp,
    }
    defaults.update(overrides)
    return defaults


def create_result_flag_payload(registration_id, flag_type, **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "flag_type": flag_type,
    }
    defaults.update(overrides)
    return defaults


def create_protest_payload(race_id, registration_id, timing_read_id,
                           requested_action, reason, **overrides) -> dict:
    defaults = {
        "race_id": race_id,
        "registration_id": registration_id,
        "timing_read_id": timing_read_id,
        "requested_action": requested_action,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_correction_payload(race_id, timing_read_id, kind, reason,
                              **overrides) -> dict:
    defaults = {
        "race_id": race_id,
        "timing_read_id": timing_read_id,
        "kind": kind,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults
