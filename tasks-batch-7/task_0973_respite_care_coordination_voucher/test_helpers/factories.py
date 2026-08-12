"""Payload factories — one per entity, input fields only (PRD §3.x, §4)."""
from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "fiscal_year_start": TEST_DEFAULTS["FISCAL_YEAR_START"],
        "total_budget_cents": TEST_DEFAULTS["TOTAL_BUDGET_CENTS"],
        "quarterly_cap_hours": TEST_DEFAULTS["QUARTERLY_CAP_HOURS"],
        "annual_cap_hours": TEST_DEFAULTS["ANNUAL_CAP_HOURS"],
        "standard_rate_cents_per_hour": TEST_DEFAULTS["STANDARD_RATE_CENTS_PER_HOUR"],
        "emergency_reserve_hours": TEST_DEFAULTS["EMERGENCY_RESERVE_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_caregiver_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ann Care",
        "email": "ann@x.com",
        "care_recipient_name": "Bob Care",
        "care_recipient_condition": "dementia",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {"need_score": 8}
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "name": "Prov A",
        "credential_level": "STANDARD",
        "service_zip": "94110",
    }
    defaults.update(overrides)
    return defaults


def create_window_payload(start_at, end_at, capacity=1, **overrides) -> dict:
    defaults = {"start_at": start_at, "end_at": end_at, "capacity": capacity}
    defaults.update(overrides)
    return defaults


def create_voucher_payload(allocation_id, caregiver_id, authorized_hours, **overrides) -> dict:
    defaults = {
        "allocation_id": allocation_id,
        "caregiver_id": caregiver_id,
        "authorized_hours": authorized_hours,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(voucher_id, caregiver_id, start_at, end_at,
                           match_mode="EXPLICIT", **overrides) -> dict:
    defaults = {
        "voucher_id": voucher_id,
        "caregiver_id": caregiver_id,
        "match_mode": match_mode,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_emergency_request_payload(caregiver_id, needed_start_at, needed_end_at,
                                     reason="caregiver hospitalized", **overrides) -> dict:
    defaults = {
        "caregiver_id": caregiver_id,
        "needed_start_at": needed_start_at,
        "needed_end_at": needed_end_at,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(rating=5, would_rebook=True, **overrides) -> dict:
    defaults = {"rating": rating, "would_rebook": would_rebook}
    defaults.update(overrides)
    return defaults
