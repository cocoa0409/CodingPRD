"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import (
    DEFAULT_BUDGET_CENTS, DEFAULT_POSITIONS, DEFAULT_STIPEND_CENTS,
    YEAR_END, YEAR_LABEL, YEAR_START,
)

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_program_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "name": f"Metro IM {i}",
        "specialty": "INTERNAL_MEDICINE",
        "acgme_program_code": f"140-00-{1000 + i}",
    }
    defaults.update(overrides)
    return defaults


def create_year_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "year_label": YEAR_LABEL,
        "start_date": YEAR_START,
        "end_date": YEAR_END,
    }
    defaults.update(overrides)
    return defaults


def create_complement_payload(program_id, academic_year_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "academic_year_id": academic_year_id,
        "pgy_level": 1,
        "approved_positions": DEFAULT_POSITIONS,
        "annual_funding_budget_cents": DEFAULT_BUDGET_CENTS,
        "blended_stipend_cents": DEFAULT_STIPEND_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(program_id, entry_academic_year_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "program_id": program_id,
        "entry_academic_year_id": entry_academic_year_id,
        "pgy_level": 1,
        "full_name": f"Resident {i}",
        "email": f"resident{i}@example.org",
        "hire_date": "2026-07-01",
        "expected_graduation_date": "2029-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_rotation_payload(program_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "program_id": program_id,
        "name": f"Wards {i}",
        "min_pgy_level": 1,
        "max_residents_per_block": 2,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(resident_id, schedule_block_id, rotation_id) -> dict:
    return {
        "resident_id": resident_id,
        "schedule_block_id": schedule_block_id,
        "rotation_id": rotation_id,
    }


def create_duty_log_payload(resident_id, started_at, ended_at) -> dict:
    return {
        "resident_id": resident_id,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def create_moonlighting_payload(resident_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "resident_id": resident_id,
        "type": "EXTERNAL",
        "site_name": f"Clinic {i}",
        "start_date": "2026-09-01",
        "end_date": "2026-10-01",
        "hours_per_week": 4.00,
    }
    defaults.update(overrides)
    return defaults


def six_ratings(level=3, patient_care=None) -> list:
    """A complete six-competency rating set (PRD §3.7)."""
    from .constants import COMPETENCIES
    return [
        {"competency": c,
         "level": patient_care if (c == "PATIENT_CARE" and patient_care is not None) else level}
        for c in COMPETENCIES
    ]


def create_evaluation_payload(resident_id, academic_year_id, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "academic_year_id": academic_year_id,
        "reporting_period": "H1",
        "competency_ratings": six_ratings(3),
    }
    defaults.update(overrides)
    return defaults


def create_ccc_review_payload(resident_id, academic_year_id, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "academic_year_id": academic_year_id,
        "reporting_period": "H1",
    }
    defaults.update(overrides)
    return defaults


def finalize_ccc_payload(outcome="SATISFACTORY", level=3) -> dict:
    return {"outcome": outcome, "milestone_levels": six_ratings(level)}


def create_case_log_payload(resident_id, rotation_id, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "rotation_id": rotation_id,
        "procedure_category": "MAJOR_SURGERY",
        "performed_date": "2026-08-03",
        "role": "SURGEON",
    }
    defaults.update(overrides)
    return defaults


def create_case_requirement_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "procedure_category": "MAJOR_SURGERY",
        "required_count": 2,
        "required_primary_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_remediation_payload(resident_id, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "goals": "Improve sign-out documentation",
        "start_date": "2026-08-01",
        "end_date": "2026-10-30",
    }
    defaults.update(overrides)
    return defaults


def create_probation_payload(resident_id, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "reason": "Unprofessional conduct",
    }
    defaults.update(overrides)
    return defaults


def create_citation_payload(program_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "program_id": program_id,
        "citation_code": f"IV.A.{i % 9 + 1}",
        "severity": "SERIOUS",
        "area_code": "DUTY_HOURS",
        "due_date": "2026-12-01",
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(program_id, academic_year_id) -> dict:
    return {"program_id": program_id, "academic_year_id": academic_year_id}


def close_survey_payload(resident_response_rate=85.00, faculty_response_rate=90.00,
                         area_results=None) -> dict:
    return {
        "resident_response_rate": resident_response_rate,
        "faculty_response_rate": faculty_response_rate,
        "area_results": area_results if area_results is not None else [],
    }
