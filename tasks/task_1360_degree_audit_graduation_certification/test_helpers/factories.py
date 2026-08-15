"""Payload factories — one per entity, input fields only (PRD §3).

Each factory ships sensible defaults so tests override only the values that
matter to the claim under test.
"""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_program_payload(**overrides) -> dict:
    defaults = {
        "program_code": _uniq("BS"),
        "name": "Bachelor of Science",
        "degree_type": "BACHELOR",
        "min_total_credits": 3,
        "min_gpa": 2.0,
        "catalog_year_start": 2024,
        "catalog_year_end": 2028,
    }
    defaults.update(overrides)
    return defaults


def create_requirement_group_payload(**overrides) -> dict:
    defaults = {
        "group_code": _uniq("GRP"),
        "required_credits": 3,
        "min_grade": "C",
        "eligible_course_codes": [],
    }
    defaults.update(overrides)
    return defaults


def create_honors_policy_payload(**overrides) -> dict:
    defaults = {
        "honors_gpa_basis": "INSTITUTIONAL",
        "cum_threshold": 3.5,
        "magna_threshold": 3.75,
        "summa_threshold": 3.9,
        "effective_first_year": 2024,
        "effective_last_year": 2027,
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(**overrides) -> dict:
    defaults = {
        "course_code": _uniq("CS"),
        "title": "Test Course",
        "credits": TEST_DEFAULTS["COURSE_CREDITS"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {
        "student_number": _uniq("S"),
        "legal_name": "Test Student",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(course_id: str, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "term": "2024-FA",
    }
    defaults.update(overrides)
    return defaults


def create_student_program_payload(program_id: str, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "catalog_year": 2024,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(audit_kind: str, expected_student_program_version: int, **overrides) -> dict:
    defaults = {
        "audit_kind": audit_kind,
        "expected_student_program_version": expected_student_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(requirement_group_id: str, kind: str, **overrides) -> dict:
    defaults = {
        "requirement_group_id": requirement_group_id,
        "kind": kind,
        "reason": "test exception",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "expected_term": TEST_DEFAULTS["EXPECTED_TERM"],
        "expected_conferral_date": TEST_DEFAULTS["EXPECTED_CONFERRAL_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(decision: str, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_reissue_payload(reason: str, **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults
