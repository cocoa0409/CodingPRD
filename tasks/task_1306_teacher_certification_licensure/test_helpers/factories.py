"""Payload factories — one per entity, input fields only (PRD sections 3-4)."""
import uuid


def _uniq_email() -> str:
    return f"user-{uuid.uuid4().hex[:12]}@example.com"


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Applicant",
        "email": _uniq_email(),
        "date_of_birth": "1990-01-01T00:00:00Z",
        "ssn_last4": "1234",
        "moral_character_attestation": True,
    }
    defaults.update(overrides)
    return defaults


def create_program_payload(**overrides) -> dict:
    defaults = {
        "institution_name": "State Teachers College",
        "program_code": f"STC-{uuid.uuid4().hex[:6].upper()}",
        "approved_subject_areas": ["MATHEMATICS"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(applicant_id, **overrides) -> dict:
    defaults = {
        "applicant_id": applicant_id,
        "pathway": "RECIPROCITY",
        "subject_area": "MATHEMATICS",
        "grade_band": "G7_12",
    }
    defaults.update(overrides)
    return defaults


def create_transcript_payload(**overrides) -> dict:
    defaults = {
        "institution_name": "State University",
        "degree_level": "BACHELORS",
        "total_semester_hours": 120,
        "courses": [
            {"course_code": "MATH101", "credit_hours": 3, "letter_grade": "A"},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_test_score_payload(**overrides) -> dict:
    defaults = {
        "exam_code": "PRAXIS_SUBJECT",
        "raw_score": 60,
        "tested_on": "2026-07-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_background_check_payload(**overrides) -> dict:
    defaults = {"adverse_findings": []}
    defaults.update(overrides)
    return defaults


def create_reciprocity_evaluation_payload(**overrides) -> dict:
    defaults = {
        "source_state": "TX",
        "source_license_type": "STANDARD",
        "years_teaching": 5,
    }
    defaults.update(overrides)
    return defaults


def create_emergency_permit_payload(**overrides) -> dict:
    defaults = {
        "district_code": "D01",
        "valid_from": "2026-09-01T00:00:00Z",
        "valid_until": "2027-03-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_endorsement_payload(**overrides) -> dict:
    defaults = {"subject_area": "SPECIAL_EDUCATION", "grade_band": "PK_6"}
    defaults.update(overrides)
    return defaults


def create_ce_credit_payload(**overrides) -> dict:
    defaults = {
        "provider_name": "CE Provider",
        "category": "CONTENT",
        "hours": 10,
        "earned_on": "2027-01-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ce_audit_payload(**overrides) -> dict:
    defaults = {"audit_variant": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_misconduct_case_payload(**overrides) -> dict:
    defaults = {"allegation_category": "INCOMPETENCE"}
    defaults.update(overrides)
    return defaults


def create_disciplinary_action_payload(**overrides) -> dict:
    defaults = {"sanction_type": "REPRIMAND"}
    defaults.update(overrides)
    return defaults
