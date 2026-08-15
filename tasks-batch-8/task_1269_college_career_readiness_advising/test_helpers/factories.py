"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools
import uuid

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    """Unique suffix so several resources of one kind coexist in a test."""
    return f"{prefix}-{next(_counter)}-{uuid.uuid4().hex[:8]}"


def create_advisor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Advisor One",
        "email": f"{_uniq('advisor')}@district.org",
        "max_caseload": 50,
    }
    defaults.update(overrides)
    return defaults


def create_teacher_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Teacher One",
        "department": "ELA",
        "max_active_letters": 5,
    }
    defaults.update(overrides)
    return defaults


def create_pathway_payload(**overrides) -> dict:
    defaults = {
        "pathway_code": _uniq("PW").upper().replace("-", "_"),
        "name": "General Pathway",
        "required_course_codes": [],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {
        "student_ref": _uniq("S"),
        "full_name": "Student One",
        "grade_level": 12,
        "demographic_group": "GROUP_A",
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(pathway_id, expected_student_version, **overrides) -> dict:
    defaults = {
        "pathway_id": pathway_id,
        "expected_student_version": expected_student_version,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(plan_id, course_code, credits, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "course_code": course_code,
        "term": "2026-SPRING",
        "credits": credits,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "college_name": "State University",
        "program_type": "COLLEGE_4YR",
        "deadline_at": "2026-06-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(kind, due_at, **overrides) -> dict:
    defaults = {"kind": kind, "due_at": due_at}
    defaults.update(overrides)
    return defaults


def create_rec_request_payload(teacher_id, due_at, **overrides) -> dict:
    defaults = {"teacher_id": teacher_id, "due_at": due_at}
    defaults.update(overrides)
    return defaults


def create_certification_payload(cert_code, **overrides) -> dict:
    defaults = {"cert_code": cert_code}
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    defaults = {
        "site_code": _uniq("SITE").upper().replace("-", "_"),
        "name": "Work Site",
        "max_concurrent_placements": 10,
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(site_id, term_start, term_end, hours_per_week,
                             **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "term_start": term_start,
        "term_end": term_end,
        "hours_per_week": hours_per_week,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(auditor_advisor_id, **overrides) -> dict:
    defaults = {"auditor_advisor_id": auditor_advisor_id}
    defaults.update(overrides)
    return defaults


def create_outcome_payload(**overrides) -> dict:
    defaults = {
        "outcome_type": "ENROLLED_4YR",
        "reported_at": "2026-05-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
