"""Entity assertions and small comparison helpers.

Structural assertions only check PRD-stated field presence/types (sections
2.2-2.4 and the field names in section 3); rule-bearing values are asserted
in the tests themselves.
"""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of fractional-digit style."""
    assert isinstance(value, str), f"expected ISO timestamp string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual, expected_iso: str, label: str = "instant"):
    """Compare two instants semantically (PRD pins instants, not string form)."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def num(value) -> float:
    """Numeric coercion for computed numeric fields (hours, gpa, risk)."""
    return float(value)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert isinstance(data["moral_character_attestation"], bool)
    assert data["status"] in (
        "REGISTERED", "APPLICATION_IN_PROGRESS", "LICENSED", "BARRED")


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["institution_name"], str) and data["institution_name"]
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert isinstance(data["approved_subject_areas"], list)
    assert data["approval_status"] in (
        "CANDIDATE", "UNDER_REVIEW", "APPROVED", "PROBATION",
        "APPROVAL_WITHDRAWN")


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["applicant_id"])
    assert data["pathway"] in (
        "TRADITIONAL", "ALTERNATIVE", "RECIPROCITY", "REINSTATEMENT")
    assert data["subject_area"] in (
        "ELEMENTARY", "MATHEMATICS", "SCIENCE", "SPECIAL_EDUCATION")
    assert data["grade_band"] in ("PK_6", "G5_8", "G7_12")
    assert isinstance(data["fee_cents"], int)
    assert data["fee_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["status"] in (
        "SUBMITTED", "INTAKE_REVIEW", "EVALUATION", "DEFICIENCY_PENDING",
        "BACKGROUND_REVIEW", "PENDING_DECISION", "APPROVED", "DENIED",
        "WITHDRAWN")
    assert isinstance(data["deficiency_hours_required"], int)


def assert_transcript(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["institution_name"], str) and data["institution_name"]
    assert data["degree_level"] in ("BACHELORS", "MASTERS", "DOCTORATE")
    assert isinstance(data["courses"], list)
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED", "REJECTED")


def assert_test_score(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert data["exam_code"] in ("PRAXIS_CORE", "PRAXIS_SUBJECT", "PEDAGOGY")
    assert isinstance(data["raw_score"], int)
    assert 0 <= data["raw_score"] <= 100
    assert data["verification_status"] in ("REPORTED", "VERIFIED", "REJECTED")


def assert_background_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["adverse_findings"], list)
    assert data["status"] in (
        "INITIATED", "PRINTS_SUBMITTED", "CLEARED", "FLAGGED", "ADJUDICATION",
        "DENIED")


def assert_reciprocity_evaluation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["source_state"], str) and len(data["source_state"]) == 2
    assert data["source_license_type"] in ("STANDARD", "PROFESSIONAL", "PROVISIONAL")
    assert isinstance(data["years_teaching"], int)
    assert isinstance(data["finalized"], bool)
    if data["finalized"]:
        assert data["outcome"] in ("FULL", "PARTIAL", "DENIED")
        assert data["mapping_mode"] in ("DETERMINISTIC", "COMMITTEE")


def assert_deficiency_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["required_hours"], int)
    assert isinstance(data["completed_hours"], (int, float))
    assert isinstance(data["extension_used"], bool)
    assert data["status"] in (
        "PROPOSED", "ACCEPTED", "IN_PROGRESS", "COMPLETED", "DEFAULTED",
        "EXTENDED", "SUPERSEDED")


def assert_license(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["applicant_id"])
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["subject_area"] in (
        "ELEMENTARY", "MATHEMATICS", "SCIENCE", "SPECIAL_EDUCATION")
    assert data["grade_band"] in ("PK_6", "G5_8", "G7_12")
    parse_instant(data["issued_on"])
    parse_instant(data["expires_on"])
    assert data["status"] in (
        "ACTIVE", "EXPIRED", "SUSPENDED", "REVOKED", "SURRENDERED")


def assert_endorsement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["license_id"])
    assert data["subject_area"] in (
        "ELEMENTARY", "MATHEMATICS", "SCIENCE", "SPECIAL_EDUCATION")
    assert data["grade_band"] in ("PK_6", "G5_8", "G7_12")
    assert data["status"] in (
        "PENDING_EVALUATION", "ACTIVE", "DENIED", "REMOVED", "REVOKED")


def assert_emergency_permit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["applicant_id"])
    assert isinstance(data["district_code"], str) and data["district_code"]
    parse_instant(data["valid_from"])
    parse_instant(data["valid_until"])
    assert data["status"] in ("ISSUED", "ACTIVE", "EXPIRED", "CONVERTED", "REVOKED")


def assert_ce_credit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["license_id"])
    assert isinstance(data["provider_name"], str) and data["provider_name"]
    assert data["category"] in ("PEDAGOGY", "CONTENT", "ETHICS", "TECHNOLOGY")
    assert num(data["hours"]) > 0
    assert data["status"] in ("SUBMITTED", "VERIFIED", "VOIDED")


def assert_ce_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["license_id"])
    assert data["audit_variant"] in ("STANDARD", "RESTORATION")
    parse_instant(data["cycle_start"])
    parse_instant(data["cycle_end"])
    assert isinstance(data["required_hours"], int)
    assert data["status"] in (
        "INITIATED", "UNDER_REVIEW", "PASSED", "FAILED", "REMEDIATION")


def assert_misconduct_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["license_id"])
    assert data["allegation_category"] in (
        "BOUNDARY_VIOLATION", "FINANCIAL_MISCONDUCT", "INCOMPETENCE",
        "CRIMINAL_CONDUCT")
    assert data["status"] in (
        "OPENED", "INVESTIGATING", "HEARING", "ADJUDICATED",
        "SANCTION_ISSUED", "DISMISSED")


def assert_disciplinary_action(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["license_id"])
    assert data["sanction_type"] in (
        "REPRIMAND", "SUSPENSION", "REVOCATION", "FINE")
    assert data["status"] in ("PROPOSED", "ISSUED", "SERVED", "VACATED")
