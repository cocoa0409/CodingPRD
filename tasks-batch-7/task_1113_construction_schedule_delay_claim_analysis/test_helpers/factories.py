"""Payload factories — one per resource, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_project_payload(**overrides) -> dict:
    defaults = {
        "project_name": TEST_DEFAULTS["PROJECT_NAME"],
        "contract_start_date": TEST_DEFAULTS["CONTRACT_START_DATE"],
        "contract_completion_date": TEST_DEFAULTS["CONTRACT_COMPLETION_DATE"],
        "liquidated_damages_daily_rate_cents": TEST_DEFAULTS["LD_DAILY_RATE_CENTS"],
        "ld_cap_cents": TEST_DEFAULTS["LD_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_schedule_version_payload(**overrides) -> dict:
    defaults = {
        "kind": "BASELINE",
        "data_date": TEST_DEFAULTS["BASELINE_DATA_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_activity_payload(**overrides) -> dict:
    defaults = {
        "activity_code": "A1000",
        "description": "Test activity",
        "original_duration_days": TEST_DEFAULTS["ACTIVITY_DURATION_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_relationship_payload(predecessor_activity_id, successor_activity_id, **overrides) -> dict:
    defaults = {
        "predecessor_activity_id": predecessor_activity_id,
        "successor_activity_id": successor_activity_id,
        "relationship_type": "FS",
        "lag_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_progress_update_payload(**overrides) -> dict:
    defaults = {
        "reporting_period_end": "2026-05-08T00:00:00Z",
        "submitted_by_contractor_user_id": "contractor-1",
    }
    defaults.update(overrides)
    return defaults


def create_progress_entry_payload(activity_id, **overrides) -> dict:
    defaults = {
        "activity_id": activity_id,
        "percent_complete": 50,
        "remaining_duration_days": 5,
        "actual_start": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_delay_event_payload(**overrides) -> dict:
    defaults = {
        "title": "Delay event",
        "causation": "OWNER_CAUSED",
        "event_start_date": "2026-05-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_eot_request_payload(delay_event_id, **overrides) -> dict:
    defaults = {
        "delay_event_id": delay_event_id,
        "requested_days": 5,
    }
    defaults.update(overrides)
    return defaults


def eot_decision_payload(expected_project_version, approved_days, awarded_cost_cents=0) -> dict:
    return {
        "expected_project_version": expected_project_version,
        "approved_days": approved_days,
        "awarded_cost_cents": awarded_cost_cents,
    }


def create_acceleration_directive_payload(**overrides) -> dict:
    defaults = {
        "directive_reference": "ACC-1",
        "directed_completion_date": "2026-07-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def acceleration_complete_payload(actual_cost_cents, measured_mile_cost_cents) -> dict:
    return {
        "actual_cost_cents": actual_cost_cents,
        "measured_mile_cost_cents": measured_mile_cost_cents,
    }


def acceleration_resolve_payload(recovery_variant, recovered_cost_cents) -> dict:
    return {
        "recovery_variant": recovery_variant,
        "recovered_cost_cents": recovered_cost_cents,
    }


def create_ld_assessment_payload(**overrides) -> dict:
    defaults = {
        "assessment_period_start": "2026-05-02T00:00:00Z",
        "assessment_period_end": "2026-05-06T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def accept_schedule_payload(expected_project_version) -> dict:
    return {"expected_project_version": expected_project_version}
