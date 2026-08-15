"""Entity assertions and domain invariant checkers (PRD 2.5, 2.6, 3.x)."""
from datetime import datetime
from typing import Any, Dict, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: Dict[str, Any], label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be a positive integer"
    )


def _assert_append_only_fields(data: Dict[str, Any], label: str) -> None:
    """PRD 2.6: Prerequisite, PlacementRecord and Payment carry only id and
    created_at — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, f"{label} must not expose updated_at (PRD 2.6)"
    assert "version" not in data, f"{label} must not expose version (PRD 2.6)"


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 UTC instants, tolerant of fractional-second rendering."""
    parsed = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    expected = datetime.fromisoformat(expected_iso.replace("Z", "+00:00"))
    assert parsed == expected, f"{label}: expected {expected_iso}, got {actual}"


def assert_high_school(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "HighSchool")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["district_code"], str) and len(data["district_code"]) > 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_term(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "AcademicTerm")
    assert data["institution_type"] in ("COLLEGE", "HIGH_SCHOOL")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    for field in ("start_date", "end_date", "add_deadline", "drop_deadline", "withdraw_deadline"):
        assert is_iso8601_timestamp(data.get(field, "")), f"AcademicTerm.{field} must be ISO 8601"
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED")


def assert_student(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Student")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_valid_uuid(data.get("high_school_id", "")), "Student.high_school_id must be a UUID"
    assert isinstance(data["grade_level"], int) and 9 <= data["grade_level"] <= 12
    assert data["status"] in ("ELIGIBLE", "SUSPENDED")
    assert isinstance(data["college_gpa"], (int, float))
    assert isinstance(data["hs_gpa"], (int, float))


def assert_course(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Course")
    assert isinstance(data["course_code"], str) and len(data["course_code"]) > 0
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["college_credit_hours"], int) and data["college_credit_hours"] >= 1
    assert data["hs_credit_units"] > 0
    assert isinstance(data["placement_exam_code"], str)
    assert isinstance(data["min_placement_score"], int) and data["min_placement_score"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_prerequisite(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "Prerequisite")
    assert is_valid_uuid(data.get("course_id", "")), "Prerequisite.course_id must be a UUID"
    assert is_valid_uuid(data.get("requires_course_id", "")), (
        "Prerequisite.requires_course_id must be a UUID"
    )
    assert data["min_grade"] in ("A", "B", "C")


def assert_placement_record(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "PlacementRecord")
    assert is_valid_uuid(data.get("student_id", "")), "PlacementRecord.student_id must be a UUID"
    assert isinstance(data["exam_code"], str) and len(data["exam_code"]) > 0
    assert isinstance(data["score"], int) and data["score"] >= 0
    assert is_iso8601_timestamp(data.get("taken_at", "")), "PlacementRecord.taken_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), (
        "PlacementRecord.expires_at must be ISO 8601"
    )


def assert_instructor(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Instructor")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_valid_uuid(data.get("high_school_id", "")), "Instructor.high_school_id must be a UUID"


def assert_credential_application(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "CredentialApplication")
    assert is_valid_uuid(data.get("instructor_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["qualification_summary"], str)
    assert data["status"] in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "NEEDS_REVISION",
        "APPROVED",
        "DENIED",
    )
    assert data.get("reviewed_by") is None or isinstance(data["reviewed_by"], str)


def assert_offering(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "CourseOffering")
    for field in ("course_id", "college_term_id", "hs_term_id", "high_school_id", "instructor_id"):
        assert is_valid_uuid(data.get(field, "")), f"CourseOffering.{field} must be a UUID"
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["delivery_mode"] in ("HS_CAMPUS", "COLLEGE_CAMPUS", "ONLINE")
    assert isinstance(data["seats_taken"], int) and data["seats_taken"] >= 0
    assert isinstance(data["seats_available"], int)
    assert data["status"] in ("DRAFT", "OPEN", "IN_SESSION", "GRADING", "FINALIZED", "CANCELLED")


def assert_enrollment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Enrollment")
    assert is_valid_uuid(data.get("student_id", "")), "Enrollment.student_id must be a UUID"
    assert is_valid_uuid(data.get("offering_id", "")), "Enrollment.offering_id must be a UUID"
    assert data["status"] in (
        "PENDING_VERIFICATION",
        "REGISTERED",
        "WAITLISTED",
        "DROPPED",
        "WITHDRAWN",
        "COMPLETED",
        "CANCELLED",
        "EXPIRED",
    )
    assert data.get("grade") is None or data["grade"] in ("A", "B", "C", "D", "F", "W")
    assert data.get("waitlist_seq") is None or isinstance(data["waitlist_seq"], int)
    assert data.get("withdrawn_at") is None or is_iso8601_timestamp(data["withdrawn_at"])


def assert_transcript_entry(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "TranscriptEntry")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["institution"] in ("COLLEGE", "HIGH_SCHOOL")
    assert data["grade"] in ("A", "B", "C", "D", "F", "W")
    assert isinstance(data["credit_value"], (int, float)) and data["credit_value"] > 0
    assert isinstance(data["grade_points"], (int, float))
    assert data["status"] in ("PENDING", "POSTED", "VOIDED")


def assert_funding_agreement(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "FundingAgreement")
    assert is_valid_uuid(data.get("high_school_id", ""))
    assert is_valid_uuid(data.get("college_term_id", ""))
    assert data["funding_model"] in ("STATE_PROGRAM", "DISTRICT_CONTRACT", "FAMILY_RESPONSIBLE")
    assert isinstance(data["tuition_cents_per_credit"], int) and data["tuition_cents_per_credit"] >= 1
    assert isinstance(data["state_rate_cents_per_credit"], int) and data["state_rate_cents_per_credit"] >= 0
    assert isinstance(data["district_cap_cents"], int) and data["district_cap_cents"] >= 0


def assert_invoice(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("funding_agreement_id", ""))
    for field in (
        "tuition_total_cents",
        "state_amount_cents",
        "district_amount_cents",
        "family_amount_cents",
        "paid_state_cents",
        "paid_district_cents",
        "paid_family_cents",
    ):
        assert isinstance(data.get(field), int) and data[field] >= 0, (
            f"Invoice.{field} must be a non-negative integer of cents"
        )
    assert data.get("refund_pct") is None or data["refund_pct"] in (0, 50, 100)
    assert data["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID", "VOIDED")
    assert data["refund_status"] in ("NONE", "DUE", "PROCESSED")


def assert_payment(data: Dict[str, Any]) -> None:
    _assert_append_only_fields(data, "Payment")
    assert is_valid_uuid(data.get("invoice_id", "")), "Payment.invoice_id must be a UUID"
    assert data["payer"] in ("STATE", "DISTRICT", "FAMILY")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_articulation_agreement(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "ArticulationAgreement")
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["target_institution"], str) and len(data["target_institution"]) > 0
    assert data["transfer_credit_hours"] > 0
    assert data["min_grade_for_transfer"] in ("A", "B", "C")
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))


def assert_seat_conservation(offering: Dict[str, Any], label: str = "CourseOffering") -> None:
    """PRD 2.5: seats_taken + seats_available == capacity at all times."""
    assert offering["seats_taken"] + offering["seats_available"] == offering["capacity"], (
        f"{label}: seats_taken ({offering['seats_taken']}) + seats_available "
        f"({offering['seats_available']}) != capacity ({offering['capacity']})"
    )


def assert_invoice_conservation(invoice: Dict[str, Any], label: str = "Invoice") -> None:
    """PRD 3.7: the three payer buckets always sum to tuition_total_cents."""
    total = (
        invoice["state_amount_cents"]
        + invoice["district_amount_cents"]
        + invoice["family_amount_cents"]
    )
    assert total == invoice["tuition_total_cents"], (
        f"{label}: state + district + family ({total}) != tuition_total_cents "
        f"({invoice['tuition_total_cents']})"
    )


def assert_entry_list(entries: List[Dict[str, Any]]) -> None:
    for entry in entries:
        assert_transcript_entry(entry)
