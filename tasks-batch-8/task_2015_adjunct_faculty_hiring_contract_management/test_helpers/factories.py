"""Payload factories — one per creatable entity, input fields only (PRD Section 4)."""
import itertools

from .constants import TERM_2026FA

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def department_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "code": f"D{n:04d}",
        "name": f"Department {n}",
        "contact_hour_value": 1.00,
    }
    defaults.update(overrides)
    return defaults


def term_payload(**overrides) -> dict:
    n = _seq()
    defaults = dict(TERM_2026FA)
    defaults["code"] = f"2{n:03d}FA"
    defaults["load_cap_units"] = 4.50
    defaults.update(overrides)
    return defaults


def rate_schedule_payload(department_id, **overrides) -> dict:
    defaults = {
        "department_id": department_id,
        "education_tier": "MASTERS",
        "rate_basis": "PER_COURSE",
        "base_rate_cents": 450000,
        "longevity_step_cents": 0,
        "longevity_step_cap": 0,
        "effective_start_date": "2026-08-01",
        "effective_end_date": "2027-01-31",
    }
    defaults.update(overrides)
    return defaults


def posting_payload(department_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "department_id": department_id,
        "term_code": "2026FA",
        "title": f"Adjunct Pool {n}",
        "min_education_tier": "MASTERS",
        "open_date": "2026-06-01",
        "close_date": "2026-07-15",
    }
    defaults.update(overrides)
    return defaults


def application_payload(posting_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "posting_id": posting_id,
        "applicant_name": f"Applicant {n}",
        "applicant_email": f"applicant{n}@example.edu",
        "claimed_education_tier": "MASTERS",
    }
    defaults.update(overrides)
    return defaults


def credential_payload(application_id, kind, **overrides) -> dict:
    n = _seq()
    defaults = {
        "application_id": application_id,
        "kind": kind,
        "evidence_ref": f"ev-{n}",
    }
    defaults.update(overrides)
    return defaults


def section_payload(department_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "department_id": department_id,
        "term_code": "2026FA",
        "course_code": f"CRS-{n:03d}",
        "section_code": "01",
        "weekly_contact_hours": 3.0,
        "credit_hours": 3,
        "enrollment": 20,
        "min_enrollment": 5,
    }
    defaults.update(overrides)
    return defaults


def contract_payload(faculty_id, section_id, rate_schedule_id, expected_faculty_version,
                     **overrides) -> dict:
    defaults = {
        "faculty_id": faculty_id,
        "section_id": section_id,
        "rate_schedule_id": rate_schedule_id,
        "expected_faculty_version": expected_faculty_version,
    }
    defaults.update(overrides)
    return defaults


def payroll_period_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "period_code": f"PP-{n:04d}",
        "start_date": "2026-08-24",
        "end_date": "2026-09-20",
    }
    defaults.update(overrides)
    return defaults


def evaluation_payload(faculty_id, **overrides) -> dict:
    defaults = {
        "faculty_id": faculty_id,
        "term_code": "2026FA",
        "teaching_score": 4.00,
        "service_score": 4.00,
        "compliance_score": 4.00,
    }
    defaults.update(overrides)
    return defaults


def retention_entry_payload(faculty_id, department_id, **overrides) -> dict:
    defaults = {
        "faculty_id": faculty_id,
        "department_id": department_id,
        "list_term_code": "2027SP",
    }
    defaults.update(overrides)
    return defaults
