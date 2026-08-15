"""Payload factories — one per entity, input fields only (PRD §3 narratives)."""

import itertools

from .constants import TEST_DEFAULTS

# Monotonic suffix so factory-built patients never trip duplicate-demographic prevention.
_counter = itertools.count(1000)


def _n() -> int:
    return next(_counter)


def create_patient_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "first_name": f"Test{n}",
        "last_name": f"Patient{n}",
        "date_of_birth": "1990-01-15",
        "sex_at_birth": "F",
        "primary_phone": f"+15557{n % 1000000:06d}"[:13],
    }
    defaults.update(overrides)
    return defaults


def complete_registration_payload(**overrides) -> dict:
    defaults = {"consent_general": True}
    defaults.update(overrides)
    return defaults


def merge_patient_payload(survivor_patient_id, expected_patient_version, **overrides) -> dict:
    defaults = {
        "survivor_patient_id": survivor_patient_id,
        "expected_patient_version": expected_patient_version,
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(patient_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "patient_id": patient_id,
        "payer_id": TEST_DEFAULTS["PAYER_ID"],
        "member_id": f"M{n}",
        "plan_type": "PPO",
        "effective_start": TEST_DEFAULTS["EFFECTIVE_START"],
        "priority_rank": 1,
        "deductible_remaining_cents": 0,
        "oop_max_remaining_cents": TEST_DEFAULTS["OOP_MAX_REMAINING_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(patient_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "patient_id": patient_id,
        "department_code": "ORTHO",
        "procedure_code": "99213",
        "scheduled_start": "2026-08-20T09:00:00Z",
        "duration_minutes": 30,
        "visit_type": "ESTABLISHED",
        "provider_code": f"DR{n}",
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_payload(policy_id, appointment_id, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "appointment_id": appointment_id,
        "coverage_status": "ACTIVE",
        "copay_cents": 0,
        "coinsurance_pct": 0,
        "auth_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(patient_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "patient_id": patient_id,
        "referring_provider_npi": f"NPI{n}",
        "specialty_code": "CARD",
        "procedure_code": "99213",
        "visits_authorized": 5,
        "valid_from": "2026-01-01",
        "valid_until": "2027-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(patient_id, appointment_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "patient_id": patient_id,
        "appointment_id": appointment_id,
        "payer_auth_number": f"AUTH{n}",
        "authorized_units": 1,
        "valid_until": "2027-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(policy_id, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "allowed_amount_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 1000,
        "method": "CARD",
        "kind": "POST",
    }
    defaults.update(overrides)
    return defaults


def create_flag_payload(**overrides) -> dict:
    defaults = {
        "flag_type": "MOBILITY",
    }
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


def call_next_payload(department_code, queue_date) -> dict:
    return {"department_code": department_code, "queue_date": queue_date}
