"""Payload factories — one per entity, input fields only.

Required input fields are always present in defaults; optional input fields
(those PRD declares with a default) are omitted unless explicitly overridden.
"""
from .constants import TEST_DEFAULTS


def create_location_payload(**overrides) -> dict:
    """Required: name, time_zone, overtime_cost_guardrail_cents.
    Optional dials (predictability_pay_enabled, advance_notice_days,
    min_rest_hours_between_shifts, overtime_weekly_threshold_hours,
    overtime_multiplier) are passed only via overrides."""
    defaults = {
        "name": "Test Location",
        "time_zone": TEST_DEFAULTS["TIME_ZONE"],
        "overtime_cost_guardrail_cents": TEST_DEFAULTS["HIGH_GUARDRAIL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_worker_payload(**overrides) -> dict:
    """Required: full_name, email, base_hourly_rate_cents.
    Optional: is_minor, minor_daily_cap_hours, minor_weekly_cap_hours (via overrides)."""
    defaults = {
        "full_name": "Test Worker",
        "email": "worker@example.com",
        "base_hourly_rate_cents": TEST_DEFAULTS["BASE_HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_availability_payload(**overrides) -> dict:
    """Required: kind, start_utc, end_utc."""
    defaults = {
        "kind": "UNAVAILABLE",
        "start_utc": "2026-06-02T10:00:00Z",
        "end_utc": "2026-06-02T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_time_off_payload(**overrides) -> dict:
    """Required: start_utc, end_utc, reason."""
    defaults = {
        "start_utc": "2026-06-10T00:00:00Z",
        "end_utc": "2026-06-11T00:00:00Z",
        "reason": "Personal",
    }
    defaults.update(overrides)
    return defaults


def create_shift_template_payload(**overrides) -> dict:
    """Required: role_name, weekday, local_start_minute, duration_minutes, forecast_headcount."""
    defaults = {
        "role_name": TEST_DEFAULTS["ROLE_NAME"],
        "weekday": 0,
        "local_start_minute": 540,
        "duration_minutes": 480,
        "forecast_headcount": 1,
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    """Required: role_name, start_utc, end_utc, headcount_required.
    Optional: template_id (via overrides)."""
    defaults = {
        "role_name": TEST_DEFAULTS["ROLE_NAME"],
        "start_utc": "2026-06-05T09:00:00Z",
        "end_utc": "2026-06-05T13:00:00Z",
        "headcount_required": 1,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(shift_id, worker_id, **overrides) -> dict:
    """Required: shift_id, worker_id. Optional: force_over_guardrail (via overrides)."""
    defaults = {"shift_id": shift_id, "worker_id": worker_id}
    defaults.update(overrides)
    return defaults


def create_bid_payload(**overrides) -> dict:
    """Optional: seniority_score (defaults to 0 server-side; passed only via overrides)."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def create_swap_payload(from_assignment_id, to_worker_id, **overrides) -> dict:
    """Required: from_assignment_id, to_worker_id."""
    defaults = {"from_assignment_id": from_assignment_id, "to_worker_id": to_worker_id}
    defaults.update(overrides)
    return defaults


def create_pay_period_payload(**overrides) -> dict:
    """Required: start_utc, end_utc."""
    defaults = {
        "start_utc": "2026-06-01T00:00:00Z",
        "end_utc": "2026-06-08T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
