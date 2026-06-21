"""Payload factories — one per entity, input fields only.

Each factory provides the PRD-required input fields with sensible defaults and
accepts **overrides for the values a test needs to control. A unique-counter is
used for naturally-unique fields (npi, cpt code, login_email) so back-to-back
factory calls within one test do not collide on uniqueness constraints.
"""
import itertools

_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


def create_provider_payload(**overrides) -> dict:
    """POST /providers input fields. npi is a 10-digit string (unique)."""
    n = _next()
    defaults = {
        "npi": f"9{n:09d}",          # 10 digits, leading 9 keeps it 10 wide
        "full_name": f"Dr Test {n}",
        "specialty": "FAMILY_MEDICINE",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    """POST /patients input fields."""
    defaults = {
        "first_name": "Test",
        "last_name": "Patient",
        "date_of_birth": "1980-01-01",
        "sex": "M",
    }
    defaults.update(overrides)
    return defaults


def create_cpt_code_payload(**overrides) -> dict:
    """POST /cpt-codes input fields. code is a 5-char string (unique)."""
    n = _next()
    # 5-char code, e.g. T0001
    code = overrides.pop("code", f"T{n:04d}")
    defaults = {
        "code": code,
        "short_description": "Test billing code",
        "category": "EM",
        "base_fee_cents": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(patient_id, provider_id, **overrides) -> dict:
    """POST /visits input fields."""
    defaults = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "visit_type": "CONSULTATION",
        "scheduled_start": "2026-06-01T09:00:00Z",
        "scheduled_end": "2026-06-01T09:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_charge_line_payload(cpt_code, **overrides) -> dict:
    """POST /visits/{id}/charge-lines input fields. visit_id comes from the path."""
    defaults = {
        "cpt_code": cpt_code,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(patient_id, provider_id, visit_id, **overrides) -> dict:
    """POST /prescriptions input fields."""
    defaults = {
        "patient_id": patient_id,
        "provider_id": provider_id,
        "visit_id": visit_id,
        "drug_name": "Amoxicillin",
        "schedule": "NON_CONTROLLED",
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(patient_id, referring_provider_id, **overrides) -> dict:
    """POST /referrals input fields."""
    defaults = {
        "patient_id": patient_id,
        "referring_provider_id": referring_provider_id,
        "target_specialty": "CARDIOLOGY",
        "priority": "ROUTINE",
    }
    defaults.update(overrides)
    return defaults


def create_portal_account_payload(patient_id, **overrides) -> dict:
    """POST /portal-accounts input fields. login_email is unique."""
    n = _next()
    defaults = {
        "patient_id": patient_id,
        "login_email": f"portal{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_hedis_measure_payload(patient_id, **overrides) -> dict:
    """POST /hedis-measures input fields."""
    defaults = {
        "patient_id": patient_id,
        "measure_type": "MED_ADHERENCE",
        "measurement_year": 2026,
        "method": "ADMINISTRATIVE",
    }
    defaults.update(overrides)
    return defaults


def record_payment_payload(amount_cents, **overrides) -> dict:
    """POST /patients/{id}/payments input fields."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
