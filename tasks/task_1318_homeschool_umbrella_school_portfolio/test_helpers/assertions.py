"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(str(data.get("id", ""))), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        str(data.get("created_at", ""))
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        str(data.get("updated_at", ""))
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_academic_year(data: dict):
    _assert_common_fields(data, "AcademicYear")
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ["PLANNING", "OPEN", "CLOSED", "REPORTED"]
    assert isinstance(data["testing_grades"], list)
    assert isinstance(data["required_instructional_days"], int)
    assert isinstance(data["required_minutes_elementary"], int)
    assert isinstance(data["required_minutes_secondary"], int)


def assert_family(data: dict):
    _assert_common_fields(data, "Family")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["district_code"], str) and data["district_code"]
    assert isinstance(data["fee_balance_cents"], int)
    assert data["fee_status"] in ["CURRENT", "OVERDUE"]


def assert_student(data: dict):
    _assert_common_fields(data, "Student")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert data["transcript_sealed"] in [True, False]


def assert_enrollment(data: dict):
    _assert_common_fields(data, "Enrollment")
    assert data["enrollment_status"] in [
        "REGISTERED", "ACTIVE", "COMPLETED", "WITHDRAWN", "GRADUATED",
    ]
    assert data["compliance_standing"] in [
        "GOOD_STANDING", "PROBATION", "NONCOMPLIANT",
    ]
    assert data["standing_locked"] in [True, False]
    assert isinstance(data["provisional_days_counted"], int)
    assert isinstance(data["provisional_minutes_credited"], int)
    assert isinstance(data["certified_days_counted"], int)
    assert isinstance(data["certified_minutes_credited"], int)
    assert data["testing_required"] in [True, False]
    assert data["testing_satisfied"] in [True, False]


def assert_notice(data: dict):
    _assert_common_fields(data, "NoticeOfIntent")
    assert data["status"] in ["DRAFT", "FILED", "ACKNOWLEDGED", "RETURNED", "WITHDRAWN"]
    assert isinstance(data["refile_count"], int)


def assert_curriculum_plan(data: dict):
    _assert_common_fields(data, "CurriculumPlan")
    assert isinstance(data["subjects"], list)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "REVISION_REQUESTED",
        "APPROVED", "AMENDMENT_REVIEW", "ARCHIVED",
    ]
    assert isinstance(data["revision_count"], int)


def assert_attendance_entry(data: dict):
    _assert_common_fields(data, "AttendanceEntry")
    assert isinstance(data["entry_date"], str)
    assert isinstance(data["minutes"], int)
    assert data["status"] in ["RECORDED", "VERIFIED", "VOIDED"]


def assert_portfolio(data: dict):
    _assert_common_fields(data, "Portfolio")
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "REMEDIATION_REQUIRED",
        "ACCEPTED", "REJECTED", "WITHDRAWN",
    ]
    assert isinstance(data["attempt_count"], int)


def assert_evaluation(data: dict):
    # Immutable row: only id and created_at among common fields (PRD §2.5).
    assert is_valid_uuid(str(data.get("id", ""))), "Evaluation.id must be a valid UUID"
    assert is_iso8601_timestamp(
        str(data.get("created_at", ""))
    ), "Evaluation.created_at must be ISO 8601"
    assert "updated_at" not in data, "Evaluation must not carry updated_at"
    assert "version" not in data, "Evaluation must not carry version"
    assert data["overall_outcome"] in ["ACCEPTED", "REMEDIATION_REQUIRED", "REJECTED"]
    assert isinstance(data["subject_scores"], list)
    assert isinstance(data["attempt_number"], int)


def assert_exam_session(data: dict):
    _assert_common_fields(data, "ExamSession")
    assert isinstance(data["test_name"], str) and data["test_name"]
    assert data["status"] in [
        "SCHEDULED", "REGISTRATION_OPEN", "REGISTRATION_CLOSED", "ADMINISTERED",
    ]
    assert isinstance(data["seats_taken"], int)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["target_grades"], list)


def assert_test_registration(data: dict):
    _assert_common_fields(data, "TestRegistration")
    assert data["status"] in [
        "REGISTERED", "ATTENDED", "NO_SHOW", "EXCUSED", "SCORED", "CANCELLED",
    ]


def assert_course_credit(data: dict):
    _assert_common_fields(data, "CourseCredit")
    assert data["subject"] in [
        "ENGLISH", "MATH", "SCIENCE", "SOCIAL_STUDIES",
        "FOREIGN_LANGUAGE", "FINE_ARTS", "PHYS_ED", "ELECTIVE",
    ]
    assert data["status"] in [
        "PLANNED", "COMPLETED", "VERIFIED", "POSTED", "REJECTED", "REVOKED",
    ]


def assert_coop_class(data: dict):
    _assert_common_fields(data, "CoopClass")
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in ["DRAFT", "OPEN", "IN_SESSION", "COMPLETED", "CANCELLED"]
    assert isinstance(data["seats_taken"], int)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["fee_base_cents"], int)
    assert isinstance(data["materials_fee_cents"], int)


def assert_coop_enrollment(data: dict):
    _assert_common_fields(data, "CoopEnrollment")
    assert data["status"] in [
        "CONFIRMED", "WAITLISTED", "DROPPED", "CANCELLED", "COMPLETED",
    ]
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["discount_pct_applied"], int)


def assert_graduation_application(data: dict):
    _assert_common_fields(data, "GraduationApplication")
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED", "DIPLOMA_ISSUED"]


def assert_compliance_report(data: dict):
    _assert_common_fields(data, "ComplianceReport")
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]
    assert isinstance(data["total_enrollments"], int)
    assert isinstance(data["compliant_count"], int)
    assert isinstance(data["noncompliant_enrollment_ids"], list)


def assert_family_ledger(data: dict):
    """Ledger read shape (PRD §3.7): balance, status, oldest unpaid charge."""
    assert isinstance(data["fee_balance_cents"], int)
    assert data["fee_status"] in ["CURRENT", "OVERDUE"]
    assert "oldest_unpaid_charge_at" in data


def assert_transcript(data: dict):
    """Computed transcript view shape (PRD §3.8)."""
    assert "official_credits_total" in data
    assert "projected_credits_total" in data
    assert "gpa_official" in data
    assert isinstance(data["subject_credits_official"], dict)
    assert data["transcript_sealed"] in [True, False]
