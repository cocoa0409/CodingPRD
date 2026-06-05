"""Payload factories — one per entity, input fields only.

Only fields a client supplies on create/edit are included. Server-computed and
system-managed fields (combined_rating_pct, status, version, ...) are never sent.
Optional fields with PRD-declared defaults (discharged_for_service_disability,
body_side, is_extremity, Yellow Ribbon school fields, tuition/requests on
enrollment, in_school_18_to_23) are omitted unless explicitly overridden.
"""
import itertools

_FILE_NUMBER_SEQ = itertools.count(1)


def unique_file_number(prefix: str = "FN-AUTO") -> str:
    """A process-unique VA file number for create-veteran calls (PRD §3.1)."""
    return f"{prefix}-{next(_FILE_NUMBER_SEQ)}"


def create_veteran_payload(**overrides) -> dict:
    """POST /veterans. Required: full_name, file_number, total_active_duty_days.

    discharged_for_service_disability is optional and defaults to false (PRD §3.1),
    so it is omitted unless overridden.
    """
    defaults = {
        "full_name": "Test Veteran",
        "file_number": unique_file_number(),
        "total_active_duty_days": 1200,
    }
    defaults.update(overrides)
    return defaults


def update_veteran_payload(expected_veteran_version: int, **overrides) -> dict:
    """PATCH /veterans/{id}. Carries expected_veteran_version (PRD §2.6) plus any
    of total_active_duty_days / discharged_for_service_disability being edited."""
    defaults = {"expected_veteran_version": expected_veteran_version}
    defaults.update(overrides)
    return defaults


def create_claim_payload(veteran_id: str, **overrides) -> dict:
    """POST /claims. Required: veteran_id, claim_type, received_date (PRD §3.3)."""
    defaults = {
        "veteran_id": veteran_id,
        "claim_type": "ORIGINAL",
        "received_date": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_condition_payload(veteran_id: str, proposed_rating_pct: int, **overrides) -> dict:
    """POST /claims/{id}/conditions. Required: veteran_id, diagnostic_code,
    proposed_rating_pct (PRD §3.3). body_side and is_extremity are optional."""
    defaults = {
        "veteran_id": veteran_id,
        "diagnostic_code": "5260",
        "proposed_rating_pct": proposed_rating_pct,
    }
    defaults.update(overrides)
    return defaults


def update_condition_payload(**overrides) -> dict:
    """PATCH /conditions/{id}. Any of proposed_rating_pct / body_side / is_extremity."""
    return dict(overrides)


def create_school_payload(**overrides) -> dict:
    """POST /schools. Required: name, is_public, monthly_housing_rate_cents (PRD §3.11).
    Yellow Ribbon fields are optional and default to false/0/0."""
    defaults = {
        "name": "Test University",
        "is_public": True,
        "monthly_housing_rate_cents": 200000,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(veteran_id: str, school_id: str, **overrides) -> dict:
    """POST /enrollments. Required: veteran_id, school_id, term_start, term_end,
    credit_hours, full_time_credit_hours (PRD §3.11). tuition_charged_cents and
    requests_yellow_ribbon are optional."""
    defaults = {
        "veteran_id": veteran_id,
        "school_id": school_id,
        "term_start": "2026-08-20T00:00:00Z",
        "term_end": "2026-12-15T00:00:00Z",
        "credit_hours": 12,
        "full_time_credit_hours": 12,
    }
    defaults.update(overrides)
    return defaults


def add_dependent_payload(relationship: str, **overrides) -> dict:
    """POST /veterans/{id}/dependents. Required: relationship. in_school_18_to_23
    is optional (CHILD only) and defaults to false (PRD §3.2)."""
    defaults = {"relationship": relationship}
    defaults.update(overrides)
    return defaults


def create_voc_rehab_plan_payload(veteran_id: str, **overrides) -> dict:
    """POST /voc-rehab-plans. Required: veteran_id, planned_months, track (PRD §3.14)."""
    defaults = {
        "veteran_id": veteran_id,
        "planned_months": 12,
        "track": "REEMPLOYMENT",
    }
    defaults.update(overrides)
    return defaults
