"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_email_counter = itertools.count(1)
_code_counter = itertools.count(1)


def unique_email(prefix: str = "stu") -> str:
    """Generate a unique student email (case-insensitive unique per PRD §3.2)."""
    return f"{prefix}{next(_email_counter)}@example.com"


def unique_code(prefix: str = "COH") -> str:
    """Generate a unique cohort code."""
    return f"{prefix}-{next(_code_counter)}"


def create_program_payload(**overrides) -> dict:
    """Program create payload. Policy ratios optional (PRD §3.1 defaults)."""
    defaults = {
        "name": "HVAC Technician",
        "credential_type": "DIPLOMA",
        "required_clock_hours": 1000,
        "required_theory_hours": 600,
        "required_externship_hours": 400,
        "tuition_cents": 900_000,
    }
    defaults.update(overrides)
    return defaults


def create_cohort_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "code": unique_code(),
        "start_term_index": 0,
        "end_term_index": 8,
        "seat_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Student",
        "email": unique_email(),
        "hs_diploma_verified": True,
    }
    defaults.update(overrides)
    return defaults


def create_externship_site_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Clinic",
        "daily_slot_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(student_id: str, cohort_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "cohort_id": cohort_id,
        "contract_tuition_cents": 500_000,
        "scheduled_aid_cents": 0,
        "cancellation_window_term_index": 0,
    }
    defaults.update(overrides)
    return defaults


def create_attendance_entry_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "term_index": 1,
        "kind": "THEORY",
        "scheduled_hours": 10,
        "attended_hours": 10,
    }
    defaults.update(overrides)
    return defaults


def create_sap_standing_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "checkpoint_term_index": 4,
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "disbursement_index": 1,
        "planned_amount_cents": 200_000,
        "required_clock_hours_gate": 0,
    }
    defaults.update(overrides)
    return defaults


def create_refund_case_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "method": "PRO_RATA",
        "withdrawal_term_index": 2,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(agreement_id: str, site_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "site_id": site_id,
        "start_term_index": 1,
        "end_term_index": 4,
        "planned_hours": 100,
    }
    defaults.update(overrides)
    return defaults


def create_exam_attempt_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "attempt_index": 1,
        "scaled_score": 720,
        "passing_score": 700,
    }
    defaults.update(overrides)
    return defaults


def create_placement_outcome_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "outcome_term_index": 9,
        "outcome_type": "EMPLOYED_IN_FIELD",
        "employer_name": "ACME Corp",
    }
    defaults.update(overrides)
    return defaults
