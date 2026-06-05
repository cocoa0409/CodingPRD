"""Payload factories — one per entity, input fields only.

Each factory returns the request body for a create/transition call. Only fields
the client supplies are present; server-computed and server-system fields are
never sent. Callers pass **overrides to control the values a test exercises.
"""
from .constants import (
    FPL_YEAR,
    FPL_BASE_ANNUAL_CENTS,
    FPL_PER_MEMBER_INCREMENT_CENTS,
    STATE_RULE_CA,
)


def create_fpl_schedule_payload(**overrides) -> dict:
    defaults = {
        "year": FPL_YEAR,
        "base_annual_cents": FPL_BASE_ANNUAL_CENTS,
        "per_member_increment_cents": FPL_PER_MEMBER_INCREMENT_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_state_rule_payload(**overrides) -> dict:
    defaults = dict(STATE_RULE_CA)
    defaults.update(overrides)
    return defaults


def create_household_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "fpl_year": FPL_YEAR,
        "primary_applicant_name": "Test Applicant",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "age": 30,
        "relationship": "SELF",
    }
    defaults.update(overrides)
    return defaults


def create_income_source_payload(**overrides) -> dict:
    defaults = {
        "income_type": "WAGES",
        "monthly_amount_cents": 120000,
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(**overrides) -> dict:
    defaults = {
        "asset_type": "CASH",
        "value_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "pathway": "MAGI",
        "magi_variant": "POINT_IN_TIME",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(household_id, application_id, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "application_id": application_id,
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2026-12-31T00:00:00Z",
        "redetermination_due": "2026-11-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_redetermination_payload(enrollment_id, new_determination_id,
                                   expected_enrollment_version, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "window_open": "2026-11-01T00:00:00Z",
        "window_close": "2026-12-15T00:00:00Z",
        "new_determination_id": new_determination_id,
        "expected_enrollment_version": expected_enrollment_version,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(enrollment_id, redetermination_id,
                          expected_enrollment_version, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "redetermination_id": redetermination_id,
        "expected_enrollment_version": expected_enrollment_version,
    }
    defaults.update(overrides)
    return defaults
