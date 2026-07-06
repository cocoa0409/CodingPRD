"""Payload factories — one per entity, input fields only."""


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Wave",
        "region_code": "R1",
        "default_language": "EN",
        "supported_languages": ["EN"],
    }
    defaults.update(overrides)
    return defaults


def create_area_payload(**overrides) -> dict:
    defaults = {
        "area_code": "A1",
        "budget_cents": 1_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_enumerator_payload(**overrides) -> dict:
    defaults = {
        "full_name": "E1",
        "languages": ["EN"],
        "hourly_rate_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "address": "1 A St",
        "respondent_language": "EN",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(enumerator_id: str, expected_case_version: int, **overrides) -> dict:
    defaults = {
        "enumerator_id": enumerator_id,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_attempt_payload(**overrides) -> dict:
    defaults = {
        "mode": "IN_PERSON",
        "window_start": "2026-03-01T10:00:00Z",
        "window_end": "2026-03-01T10:30:00Z",
        "disposition": "NO_ONE_HOME",
        "mileage_miles": 0,
    }
    defaults.update(overrides)
    return defaults


def create_response_payload(**overrides) -> dict:
    defaults = {
        "mode": "IN_PERSON",
        "language_used": "EN",
        "duration_minutes": 20,
        "flagged_answer_count": 0,
        "gps_variance_meters": 0,
    }
    defaults.update(overrides)
    return defaults


def create_reinterview_payload(reviewer_enumerator_id: str, **overrides) -> dict:
    defaults = {
        "reviewer_enumerator_id": reviewer_enumerator_id,
        "reason": "RANDOM_SAMPLE",
    }
    defaults.update(overrides)
    return defaults


def finalize_payload(outcome: str, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_pay_period_payload(**overrides) -> dict:
    defaults = {"label": "2026-W09"}
    defaults.update(overrides)
    return defaults


def create_pay_line_payload(enumerator_id: str, line_type: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "enumerator_id": enumerator_id,
        "line_type": line_type,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults
