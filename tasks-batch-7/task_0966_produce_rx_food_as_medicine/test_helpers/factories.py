"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_npi_counter = itertools.count(1111111111)


def next_npi() -> str:
    """Distinct NPI per clinic so uniqueness checks never collide within a test."""
    return str(next(_npi_counter))


def create_program_payload(**overrides) -> dict:
    """Canonical program payload (PRD §3.1 creation inputs)."""
    defaults = {
        "name": "P",
        "start_date": "2026-05-01",
        "end_date": "2026-10-31",
        "base_monthly_benefit_cents": 10000,
        "household_increment_cents": 2500,
        "max_household_size": 6,
        "double_up_multiplier": 1.0,
        "double_up_daily_cap_cents": 100000,
        "double_up_pool_cents": 200000,
        "tier2_completions": 3,
        "tier3_completions": 6,
        "renewal_window_days": 30,
        "outcome_improvement_threshold": 0.5,
    }
    defaults.update(overrides)
    return defaults


def create_funder_payload(**overrides) -> dict:
    defaults = {
        "name": "F1",
        "contact_email": "f1@x.org",
        "total_commitment_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_funding_pool_payload(program_id, funder_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "funder_id": funder_id,
        "committed_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_clinic_payload(**overrides) -> dict:
    defaults = {
        "name": "C1",
        "npi_number": next_npi(),
        "max_active_referrals": 50,
    }
    defaults.update(overrides)
    return defaults


def create_retailer_payload(**overrides) -> dict:
    defaults = {
        "name": "R1",
        "kind": "GROCERY",
        "double_up_eligible": True,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(clinic_id, **overrides) -> dict:
    defaults = {
        "clinic_id": clinic_id,
        "full_name": "Pat One",
        "date_of_birth": "1980-01-15",
        "household_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(clinic_id, patient_id, program_id, **overrides) -> dict:
    defaults = {
        "clinic_id": clinic_id,
        "patient_id": patient_id,
        "program_id": program_id,
        "diagnosis_code": "E11.9",
        "priority": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "period_index": 1,
        "start_date": "2026-05-01",
        "end_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_redemption_payload(retailer_id, enrollment_id, lines=None, **overrides) -> dict:
    if lines is None:
        lines = [
            {"category": "PRODUCE_ELIGIBLE", "amount_cents": 2000},
            {"category": "STAPLE", "amount_cents": 3000},
        ]
    defaults = {
        "retailer_id": retailer_id,
        "enrollment_id": enrollment_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_education_session_payload(**overrides) -> dict:
    defaults = {
        "topic": "T",
        "venue": "RM-1",
        "starts_at": "2026-05-10T10:00:00Z",
        "ends_at": "2026-05-10T11:00:00Z",
        "capacity": 10,
        "educator_ref": "ed-1",
    }
    defaults.update(overrides)
    return defaults


def create_completion_payload(enrollment_id, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "minutes_attended": 60,
        "passed": True,
    }
    defaults.update(overrides)
    return defaults


def create_biometric_reading_payload(**overrides) -> dict:
    defaults = {
        "kind": "A1C",
        "value": 8.0,
        "measured_at": "2026-05-10T00:00:00Z",
        "source": "LAB_VERIFIED",
    }
    defaults.update(overrides)
    return defaults


def create_funder_report_payload(funding_pool_id, expected_program_version, **overrides) -> dict:
    defaults = {
        "funding_pool_id": funding_pool_id,
        "period_start": "2026-05-01",
        "period_end": "2026-06-01",
        "basis": "CASH",
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_renewal_payload(expected_enrollment_version, **overrides) -> dict:
    defaults = {
        "reason": "renewal request",
        "expected_enrollment_version": expected_enrollment_version,
    }
    defaults.update(overrides)
    return defaults
