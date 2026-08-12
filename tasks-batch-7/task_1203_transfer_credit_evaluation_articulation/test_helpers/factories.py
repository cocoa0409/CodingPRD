"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PARTNER_NAME": "State University",
    "PARTNER_CODE": "SU",
    "CREDIT_SYSTEM": "SEMESTER",
    "COURSE_CODE": "MATH-150",
    "COURSE_TITLE": "Calculus I",
    "COURSE_HOURS": 4.0,
    "COURSE_LEVEL": "LOWER",
    "DEPARTMENT": "MATH",
    "PROGRAM_SCOPE": "ALL",
    "AGREEMENT_START": "2024-08-01",
    "AGREEMENT_END": "2027-07-31",
    "EQ_FROM": "2024-08-01",
    "EQ_UNTIL": "2027-07-31",
    "EXTERNAL_CODE": "M-101",
    "EXTERNAL_TITLE": "Calc",
    "EXTERNAL_HOURS": 4.0,
    "STUDENT_NAME": "Sam Transfer",
    "STUDENT_MAJOR": "MATH",
    "CATALOG_YEAR": 2026,
    "TERM_COMPLETED": "2025-06-15",
    "SYLLABUS_REF": "s3://syllabi/default.pdf",
}

_email_counter = [0]


def _unique_email() -> str:
    _email_counter[0] += 1
    return f"student{_email_counter[0]}@example.edu"


def create_partner_institution_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PARTNER_NAME"],
        "institution_code": DEFAULTS["PARTNER_CODE"],
        "credit_system": DEFAULTS["CREDIT_SYSTEM"],
    }
    defaults.update(overrides)
    return defaults


def create_internal_course_payload(**overrides) -> dict:
    defaults = {
        "course_code": DEFAULTS["COURSE_CODE"],
        "title": DEFAULTS["COURSE_TITLE"],
        "credit_hours": DEFAULTS["COURSE_HOURS"],
        "level": DEFAULTS["COURSE_LEVEL"],
        "department": DEFAULTS["DEPARTMENT"],
        "gened_tags": [],
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(partner_institution_id, **overrides) -> dict:
    defaults = {
        "partner_institution_id": partner_institution_id,
        "program_scope": DEFAULTS["PROGRAM_SCOPE"],
        "effective_start": DEFAULTS["AGREEMENT_START"],
        "effective_end": DEFAULTS["AGREEMENT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_equivalency_payload(internal_course_id, expected_agreement_version, **overrides) -> dict:
    defaults = {
        "internal_course_id": internal_course_id,
        "external_course_code": DEFAULTS["EXTERNAL_CODE"],
        "external_title": DEFAULTS["EXTERNAL_TITLE"],
        "external_credit_hours": DEFAULTS["EXTERNAL_HOURS"],
        "effective_from": DEFAULTS["EQ_FROM"],
        "effective_until": DEFAULTS["EQ_UNTIL"],
        "expected_agreement_version": expected_agreement_version,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["STUDENT_NAME"],
        "email": _unique_email(),
        "declared_major": DEFAULTS["STUDENT_MAJOR"],
        "catalog_year": DEFAULTS["CATALOG_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_transcript_course_payload(**overrides) -> dict:
    defaults = {
        "external_course_code": DEFAULTS["EXTERNAL_CODE"],
        "title": DEFAULTS["EXTERNAL_TITLE"],
        "credit_hours": DEFAULTS["EXTERNAL_HOURS"],
        "grade": "A",
    }
    defaults.update(overrides)
    return defaults


def create_transcript_payload(student_id, partner_institution_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "partner_institution_id": partner_institution_id,
        "term_completed": DEFAULTS["TERM_COMPLETED"],
        "courses": [create_transcript_course_payload()],
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(student_id, transcript_id, **overrides) -> dict:
    defaults = {"student_id": student_id, "transcript_id": transcript_id}
    defaults.update(overrides)
    return defaults


def create_petition_payload(line_item_id, proposed_internal_course_id, **overrides) -> dict:
    defaults = {
        "line_item_id": line_item_id,
        "proposed_internal_course_id": proposed_internal_course_id,
        "syllabus_ref": DEFAULTS["SYLLABUS_REF"],
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(petition_id, **overrides) -> dict:
    defaults = {
        "petition_id": petition_id,
        "grounds": "Appeal grounds with sufficient length",
    }
    defaults.update(overrides)
    return defaults


def create_pla_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "source_type": "MILITARY_JST",
        "credential_ref": "JST-001",
        "claimed_credits": 4.0,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_guide_payload(partner_institution_id, **overrides) -> dict:
    defaults = {
        "partner_institution_id": partner_institution_id,
        "catalog_year": DEFAULTS["CATALOG_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(**overrides) -> dict:
    defaults = {
        "effective_start": "2027-07-31",
        "effective_end": "2029-07-31",
    }
    defaults.update(overrides)
    return defaults
