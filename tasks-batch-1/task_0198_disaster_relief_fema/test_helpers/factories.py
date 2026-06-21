"""Payload factories — one per entity, input fields only.

Each factory returns a payload dict carrying the PRD-declared source:input fields
with sensible defaults; pass overrides to control specific values. Optional fields
(travel_buffer_minutes, can_approve_awards, habitability inputs only at inspect,
requested_repair_cost_cents, sba_loan_amount_cents) are omitted unless overridden.
"""
from .constants import DEFAULT_IHP_MAX_GRANT_CENTS


# Default incident window / deadline used across the suite.
DEFAULTS = {
    "INCIDENT_START": "2026-01-01T00:00:00Z",
    "INCIDENT_END": "2026-02-28T23:59:59Z",
    "REGISTRATION_DEADLINE": "2026-03-31T23:59:59Z",
    "DAMAGE_DATE": "2026-01-15T00:00:00Z",
}


def create_declaration_payload(**overrides) -> dict:
    payload = {
        "title": "DR-Test Storms",
        "incident_start": DEFAULTS["INCIDENT_START"],
        "incident_end": DEFAULTS["INCIDENT_END"],
        "ihp_max_grant_cents": DEFAULT_IHP_MAX_GRANT_CENTS,
        "registration_deadline": DEFAULTS["REGISTRATION_DEADLINE"],
    }
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Inspector",
        "badge_number": "INS-TEST",
    }
    payload.update(overrides)
    return payload


def create_caseworker_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Caseworker",
        "employee_id": "CW-TEST",
    }
    payload.update(overrides)
    return payload


def create_applicant_payload(declaration_id: str, **overrides) -> dict:
    payload = {
        "declaration_id": declaration_id,
        "household_name": "Test Household",
        "household_size": 2,
        "annual_income_cents": 3_000_000,
        "damage_date": DEFAULTS["DAMAGE_DATE"],
        "reported_repair_cost_cents": 1_000_000,
        "reported_personal_property_cents": 500_000,
        "reported_rental_months": 3,
    }
    payload.update(overrides)
    return payload


def create_assessment_payload(applicant_id: str, inspector_id: str, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "inspector_id": inspector_id,
        "scheduled_start": "2026-02-11T09:00:00Z",
        "scheduled_end": "2026-02-11T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def inspect_assessment_payload(**overrides) -> dict:
    payload = {
        "habitability": "UNINHABITABLE",
        "verified_repair_cost_cents": 1_000_000,
        "verified_personal_property_cents": 500_000,
        "verified_rental_months": 3,
    }
    payload.update(overrides)
    return payload


def create_ihp_case_payload(applicant_id: str, assessment_id: str, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "assessment_id": assessment_id,
        "monthly_fmr_cents": 100_000,
    }
    payload.update(overrides)
    return payload


def create_dob_record_payload(applicant_id: str, **overrides) -> dict:
    payload = {
        "applicant_id": applicant_id,
        "source_type": "INSURANCE",
        "amount_cents": 400_000,
        "received_at": "2026-02-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_appeal_payload(ihp_case_id: str, expected_ihp_case_version: int, **overrides) -> dict:
    payload = {
        "ihp_case_id": ihp_case_id,
        "expected_ihp_case_version": expected_ihp_case_version,
        "reason": "Test appeal reason",
    }
    payload.update(overrides)
    return payload


def create_sba_referral_payload(ihp_case_id: str, **overrides) -> dict:
    payload = {"ihp_case_id": ihp_case_id}
    payload.update(overrides)
    return payload


def create_disbursement_payload(ihp_case_id: str, line_item_id: str,
                                expected_ihp_case_version: int, **overrides) -> dict:
    payload = {
        "ihp_case_id": ihp_case_id,
        "line_item_id": line_item_id,
        "expected_ihp_case_version": expected_ihp_case_version,
        "amount_cents": 100_000,
    }
    payload.update(overrides)
    return payload


def create_rental_period_payload(ihp_case_id: str, **overrides) -> dict:
    payload = {
        "ihp_case_id": ihp_case_id,
        "period_start": "2026-03-01T00:00:00Z",
        "period_end": "2026-04-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload
