"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULTS, COURSE_DEFAULTS, FACULTY_DEFAULTS

_email_counter = [0]
_course_counter = [0]


def _unique_email(base: str = "anna") -> str:
    _email_counter[0] += 1
    return f"{base}{_email_counter[0]}@x.edu"


def _unique_course_code(base: str = "CS") -> str:
    _course_counter[0] += 1
    return f"{base}-{300 + _course_counter[0]}"


def create_term_payload(**overrides) -> dict:
    defaults = {
        "term_code": DEFAULTS["TERM_CODE"],
        "title": DEFAULTS["TERM_TITLE"],
        "start_date": DEFAULTS["TERM_START_DATE"],
        "census_date": DEFAULTS["TERM_CENSUS_DATE"],
        "comp_budget_cents": DEFAULTS["COMP_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_faculty_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Anna Aho",
        "email": _unique_email(),
        "rank": "ASSOCIATE_PROFESSOR",
        "base_salary_cents": FACULTY_DEFAULTS["BASE_SALARY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(**overrides) -> dict:
    defaults = {
        "course_code": _unique_course_code(),
        "title": COURSE_DEFAULTS["COURSE_TITLE"],
        "course_type": COURSE_DEFAULTS["COURSE_TYPE"],
        "base_credits": COURSE_DEFAULTS["BASE_CREDITS"],
        "default_enrollment_cap": COURSE_DEFAULTS["DEFAULT_ENROLLMENT_CAP"],
        "allowed_modalities": list(COURSE_DEFAULTS["ALLOWED_MODALITIES"]),
    }
    defaults.update(overrides)
    return defaults


def create_qualification_payload(faculty_id, course_id, **overrides) -> dict:
    defaults = {
        "faculty_id": faculty_id,
        "course_id": course_id,
        "expires_on": "2027-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(term_id, course_id, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "course_id": course_id,
        "section_number": "01",
        "modality": "IN_PERSON",
        "meeting_day": "MON",
        "start_minute": 540,
        "end_minute": 600,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(section_id, faculty_id, **overrides) -> dict:
    defaults = {
        "section_id": section_id,
        "faculty_id": faculty_id,
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(term_id, faculty_id, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "faculty_id": faculty_id,
        "grant_type": "RESEARCH_BUYOUT",
        "credits_released": 3,
        "start_date": "2026-08-24",
        "end_date": "2026-12-11",
    }
    defaults.update(overrides)
    return defaults


def create_overload_request_payload(term_id, faculty_id, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "faculty_id": faculty_id,
    }
    defaults.update(overrides)
    return defaults
