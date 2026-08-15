"""Payload factories — one per creatable entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS, TIER_PKG8

_seq = itertools.count(1)


def _n() -> int:
    return next(_seq)


def create_coach_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "display_name": f"Coach {n}",
        "email": f"coach.{n}@example.com",
        "credential_level": "PCC",
        "credential_expires_on": TEST_DEFAULTS["COACH_EXPIRES_FAR"],
        "max_concurrent_clients": 10,
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "full_name": f"Client {n}",
        "email": f"client.{n}@example.com",
        "timezone": TEST_DEFAULTS["TIMEZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_program_tier_payload(**overrides) -> dict:
    n = _n()
    defaults = dict(TIER_PKG8)
    defaults["tier_code"] = f"{TIER_PKG8['tier_code']}-{n}"
    defaults.update(overrides)
    return defaults


def create_discovery_call_payload(client_id: str, coach_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "coach_id": coach_id,
        "scheduled_start": "2026-08-02T10:00:00Z",
        "duration_minutes": TEST_DEFAULTS["DISCOVERY_DURATION"],
    }
    defaults.update(overrides)
    return defaults


def create_fit_assessment_payload(**overrides) -> dict:
    defaults = {
        "scope_fit": "WITHIN_SCOPE",
        "commitment_score": 70,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(client_id: str, coach_id: str, program_tier_id: str,
                              discovery_call_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "coach_id": coach_id,
        "program_tier_id": program_tier_id,
        "discovery_call_id": discovery_call_id,
        "installment_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-08-10T10:00:00Z",
        "duration_minutes": TEST_DEFAULTS["SESSION_DURATION"],
    }
    defaults.update(overrides)
    return defaults


def create_goal_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "title": f"Goal {n}",
        "target_count": 5,
    }
    defaults.update(overrides)
    return defaults


def create_check_in_payload(**overrides) -> dict:
    defaults = {
        "check_in_date": "2026-08-04",
        "completed": True,
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(coach_id: str, **overrides) -> dict:
    n = _n()
    defaults = {
        "coach_id": coach_id,
        "title": f"Cohort {n}",
        "capacity": 3,
        "window_start": "2026-08-10",
        "window_end": "2026-09-10",
    }
    defaults.update(overrides)
    return defaults


def create_testimonial_payload(enrollment_id: str, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "outcome_rating": 5,
        "body_text": "A genuinely useful program.",
    }
    defaults.update(overrides)
    return defaults


def create_refund_request_payload(enrollment_id: str, **overrides) -> dict:
    defaults = {"enrollment_id": enrollment_id}
    defaults.update(overrides)
    return defaults


def simulate_payment_payload(enrollment_id: str, **overrides) -> dict:
    defaults = {"enrollment_id": enrollment_id, "outcome": "SUCCEEDED"}
    defaults.update(overrides)
    return defaults
