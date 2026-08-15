"""Entity assertions and domain invariant checkers."""
import re
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_name: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an int >= 1"
    )


def assert_millisecond_timestamp(value: str, field_name: str = "timestamp"):
    """Common timestamp fields carry ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str) and re.search(r"\.\d{3}Z$", value), (
        f"{field_name} must carry three fractional digits (e.g. "
        f"2026-08-01T00:00:00.000Z), got {value!r}"
    )


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equal(actual: str, expected_iso: str, label: str = "instant"):
    """Compare two logical-clock instants semantically (ISO 8601)."""
    assert isinstance(actual, str) and actual, f"{label}: expected {expected_iso}, got {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


def assert_score_equals(actual, expected, label: str = "score"):
    """Two-decimal scores compare by numeric value (85.00 == 85.0)."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert float(actual) == float(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_student(data: dict):
    _assert_common_fields(data, "Student")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["grade_level"], int) and 9 <= data["grade_level"] <= 12
    assert isinstance(data["gpa_hundredths"], int) and 0 <= data["gpa_hundredths"] <= 500
    assert data.get("verified_gpa_hundredths") is None or (
        isinstance(data["verified_gpa_hundredths"], int)
        and 0 <= data["verified_gpa_hundredths"] <= 500
    )
    assert isinstance(data["residency_state"], str) and len(data["residency_state"]) == 2
    assert data["intended_major"] in [
        "STEM", "ARTS", "BUSINESS", "HEALTH", "TRADES", "UNDECIDED",
    ]
    for field in ("household_income_cents", "efc_cents", "cost_of_attendance_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"Student.{field} must be a non-negative int"
        )
    assert isinstance(data["institution_name"], str)
    assert isinstance(data["tags"], list)
    assert data["status"] in ["ACTIVE", "ARCHIVED"]
    for field in ("total_accepted_cents", "total_disbursed_cents",
                  "aid_cap_cents", "excess_cents"):
        assert isinstance(data[field], int), f"Student.{field} must be an int"


def assert_donor(data: dict):
    _assert_common_fields(data, "Donor")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert isinstance(data["anonymous"], bool)
    assert data["report_frequency"] in ["QUARTERLY", "ANNUAL"]


def assert_fund(data: dict):
    _assert_common_fields(data, "AwardFund")
    for field in ("committed_cents", "reserved_cents", "disbursed_cents",
                  "returned_cents", "available_cents"):
        assert isinstance(data[field], int), f"AwardFund.{field} must be an int"


def assert_fund_availability_invariant(data: dict):
    """available == committed - reserved - disbursed + returned after any mutation."""
    assert_fund(data)
    expected = (
        data["committed_cents"]
        - data["reserved_cents"]
        - data["disbursed_cents"]
        + data["returned_cents"]
    )
    assert data["available_cents"] == expected, (
        f"availability identity broken: available {data['available_cents']} != "
        f"{expected} (committed {data['committed_cents']} - reserved "
        f"{data['reserved_cents']} - disbursed {data['disbursed_cents']} + "
        f"returned {data['returned_cents']})"
    )


def assert_program(data: dict):
    _assert_common_fields(data, "ScholarshipProgram")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_valid_uuid(data.get("donor_id", "")), "program.donor_id must be a UUID"
    assert is_valid_uuid(data.get("fund_id", "")), "program.fund_id must be a UUID"
    assert data["program_type"] in ["MERIT", "NEED", "HYBRID"]
    assert data["match_policy"] in ["STRICT", "HOLISTIC"]
    assert data["stacking_scope"] in ["ANNUAL", "PER_TERM"]
    assert isinstance(data["award_amount_cents"], int) and data["award_amount_cents"] > 0
    assert isinstance(data["max_recipients"], int) and data["max_recipients"] >= 1
    assert isinstance(data["min_gpa_hundredths"], int)
    assert isinstance(data["eligible_majors"], list)
    assert isinstance(data["required_tags"], list)
    assert isinstance(data["required_components"], list)
    assert data["status"] in ["DRAFT", "OPEN", "CLOSED", "ARCHIVED"]


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    assert is_valid_uuid(data.get("student_id", "")), "application.student_id UUID"
    assert is_valid_uuid(data.get("program_id", "")), "application.program_id UUID"
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "SELECTED", "WAITLISTED",
        "NOT_SELECTED", "AWARDED", "WITHDRAWN", "EXPIRED",
    ]
    assert isinstance(data["returned_count"], int) and data["returned_count"] >= 0


def assert_component(data: dict):
    _assert_common_fields(data, "ApplicationComponent")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["component_type"] in ["ESSAY", "RECOMMENDATION", "TRANSCRIPT"]
    assert isinstance(data["required"], bool)
    assert data["status"] in ["PENDING", "RECEIVED", "ACCEPTED", "REJECTED", "WAIVED"]


def assert_reminder(data: dict):
    _assert_common_fields(data, "Reminder")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["offset_code"] in ["D14", "D7", "D1"]
    assert data["status"] in ["SCHEDULED", "SENT", "SUPPRESSED"]


def assert_cycle(data: dict):
    _assert_common_fields(data, "ReviewCycle")
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["label"], str)
    assert isinstance(data["quorum_count"], int) and data["quorum_count"] >= 1
    assert isinstance(data["selection_quota"], int) and data["selection_quota"] >= 0
    assert isinstance(data["waitlist_quota"], int) and data["waitlist_quota"] >= 0
    assert data["status"] in ["SETUP", "SCORING", "DELIBERATION", "FINALIZED"]


def assert_score(data: dict):
    _assert_common_fields(data, "ReviewScore")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["reviewer_user_id"], str)
    for field in ("academic_score", "essay_score", "need_score"):
        assert isinstance(data[field], int) and 0 <= data[field] <= 100, (
            f"ReviewScore.{field} must be an int in 0..100"
        )
    assert data["status"] in ["DRAFT", "SUBMITTED", "LOCKED"]


def assert_award(data: dict):
    _assert_common_fields(data, "Award")
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["offer_status"] in [
        "OFFERED", "ACCEPTED", "DECLINED", "REVOKED", "EXPIRED",
    ]
    assert data["funding_status"] in [
        "NONE", "ENCUMBERED", "DISBURSING", "FULLY_DISBURSED", "OVER_DISBURSED",
    ]
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_disbursement(data: dict):
    _assert_common_fields(data, "Disbursement")
    assert is_valid_uuid(data.get("award_id", ""))
    assert isinstance(data["term_seq"], int) and data["term_seq"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["SCHEDULED", "SENT", "CONFIRMED", "RETURNED", "CANCELLED"]


def assert_adjustment(data: dict):
    _assert_common_fields(data, "AwardAdjustment")
    assert is_valid_uuid(data.get("award_id", ""))
    assert data["reason"] in ["OVER_AWARD", "DUPLICATE", "DATA_ERROR", "WITHDRAWAL"]
    assert isinstance(data["delta_cents"], int) and data["delta_cents"] != 0
    assert data["status"] in ["DRAFT", "PENDING_APPROVAL", "APPLIED", "REJECTED"]
    assert isinstance(data["auto_generated"], bool)


def assert_renewal_evaluation(data: dict):
    _assert_common_fields(data, "RenewalEvaluation")
    assert is_valid_uuid(data.get("award_id", ""))
    assert isinstance(data["term_label"], str)
    assert isinstance(data["reported_gpa_hundredths"], int)
    assert isinstance(data["reported_credits"], int)
    assert data["status"] in [
        "PENDING", "VERIFIED_ELIGIBLE", "VERIFIED_INELIGIBLE",
        "APPEALED", "RENEWED", "LAPSED",
    ]


def assert_letter(data: dict):
    _assert_common_fields(data, "ThankYouLetter")
    assert is_valid_uuid(data.get("award_id", ""))
    assert data["status"] in [
        "REQUIRED", "SUBMITTED", "REVISION_REQUESTED",
        "APPROVED", "DELIVERED", "WAIVED",
    ]
    assert data["auto_created"] is True


def assert_report(data: dict):
    _assert_common_fields(data, "DonorReport")
    assert is_valid_uuid(data.get("donor_id", ""))
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert data["status"] in ["DRAFT", "GENERATED", "SENT", "ACKNOWLEDGED"]
