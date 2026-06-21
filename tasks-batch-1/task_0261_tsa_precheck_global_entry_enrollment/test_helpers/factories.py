"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    defaults = {
        "code": "PRECHECK",
        "name": "TSA PreCheck",
        "base_fee_cents": TEST_DEFAULTS["BASE_FEE_CENTS"],
        "validity_years": TEST_DEFAULTS["VALIDITY_YEARS"],
        "vetting_risk_threshold": TEST_DEFAULTS["VETTING_RISK_THRESHOLD"],
        "vetting_deny_threshold": TEST_DEFAULTS["VETTING_DENY_THRESHOLD"],
        "redress_min_score": TEST_DEFAULTS["REDRESS_MIN_SCORE"],
        "renewal_window_days": TEST_DEFAULTS["RENEWAL_WINDOW_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Applicant",
        "date_of_birth": "1990-01-01",
        "citizenship": "US_CITIZEN",
    }
    defaults.update(overrides)
    return defaults


def create_center_payload(**overrides) -> dict:
    defaults = {
        "program_code": "PRECHECK",
        "name": "Test Center",
        "daily_interview_capacity": 10,
        "buffer_minutes": 0,
        "lane_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(center_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "lane_index": 0,
        "starts_at": "2026-06-20T09:00:00Z",
        "ends_at": "2026-06-20T09:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "program_code": "PRECHECK",
    }
    defaults.update(overrides)
    return defaults


def pay_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def withdraw_payload(expected_application_version, **overrides) -> dict:
    defaults = {"expected_application_version": expected_application_version}
    defaults.update(overrides)
    return defaults


def background_check_payload(**overrides) -> dict:
    defaults = {
        "criminal_hits": 0,
        "watchlist_hits": 0,
        "prior_revocations": 0,
    }
    defaults.update(overrides)
    return defaults


def appointment_payload(application_id, slot_id, expected_application_version, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "slot_id": slot_id,
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def biometric_payload(appointment_id, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "fingerprint_quality": 2,
        "photo_captured": True,
    }
    defaults.update(overrides)
    return defaults


def appeal_payload(**overrides) -> dict:
    defaults = {"filed_reason": "Test appeal reason"}
    defaults.update(overrides)
    return defaults


def decide_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def redress_payload(application_id, match_strength_score, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "trip_number": "TRIP-TEST",
        "match_strength_score": match_strength_score,
    }
    defaults.update(overrides)
    return defaults
