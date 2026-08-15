"""Payload factories — one per entity, input fields only (PRD §4 payloads)."""

DEFAULTS = {
    "MAJOR_CODE": "CS",
    "COHORT_YEAR": 2026,
    "TERM_CODE": "FA26",
    "GPA": 3.0,
    "MAX_CASELOAD": 5,
    "CATALOG_YEAR": 2024,
    "REQUIRED_CREDITS": 10,
}


def create_advisor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Advisor",
        "email": "advisor@example.edu",
        "major_codes": [DEFAULTS["MAJOR_CODE"]],
        "max_caseload": DEFAULTS["MAX_CASELOAD"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Student",
        "email": "student@example.edu",
        "major_code": DEFAULTS["MAJOR_CODE"],
        "cohort_year": DEFAULTS["COHORT_YEAR"],
        "current_term_code": DEFAULTS["TERM_CODE"],
        "gpa": DEFAULTS["GPA"],
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(student_id: str, advisor_id: str, expected_student_version, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "advisor_id": advisor_id,
        "expected_student_version": expected_student_version,
    }
    defaults.update(overrides)
    return defaults


def auto_assign_payload(student_id: str, **overrides) -> dict:
    defaults = {"student_id": student_id}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(student_id: str, advisor_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "advisor_id": advisor_id,
        "term_code": DEFAULTS["TERM_CODE"],
        "scheduled_start_at": "2026-08-01T10:00:00Z",
        "scheduled_end_at": "2026-08-01T10:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_drop_in_ticket_payload(student_id: str, **overrides) -> dict:
    defaults = {"student_id": student_id, "reason": "walk-in question"}
    defaults.update(overrides)
    return defaults


def create_referral_payload(student_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "source": "FACULTY",
        "severity": "HIGH",
        "reason": "academic concern",
    }
    defaults.update(overrides)
    return defaults


def outreach_payload(outcome: str = "NO_ANSWER", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_intervention_payload(student_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "intervention_type": "ACADEMIC_COACHING",
    }
    defaults.update(overrides)
    return defaults


def create_hold_payload(**overrides) -> dict:
    defaults = {"hold_type": "ADVISING"}
    defaults.update(overrides)
    return defaults


def course(course_code: str, credits: float) -> dict:
    return {"course_code": course_code, "credits": credits}


def term(term_code: str, *courses: dict) -> dict:
    return {"term_code": term_code, "courses": list(courses)}


def create_degree_plan_payload(**overrides) -> dict:
    defaults = {
        "catalog_year": DEFAULTS["CATALOG_YEAR"],
        "required_credits": DEFAULTS["REQUIRED_CREDITS"],
        "terms": [
            term(
                DEFAULTS["TERM_CODE"],
                course("BIO1", 3.5),
                course("CHM1", 3.5),
                course("MAT1", 3.5),
            )
        ],
    }
    defaults.update(overrides)
    return defaults


def create_note_payload(**overrides) -> dict:
    defaults = {"visibility": "SHARED", "body": "advising note body"}
    defaults.update(overrides)
    return defaults
