"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ApplicationRound,
    ApplicationStatus,
    AwardStatus,
    ContractStatus,
    CycleStatus,
    EvaluationKind,
    EvaluationStatus,
    GradeLevel,
    ReenrollmentOfferStatus,
    StudentSource,
    StudentStatus,
    VerificationStatus,
)


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def _assert_enum(value, enum_cls, label: str):
    assert value in {member.value for member in enum_cls}, (
        f"{label} must be one of {[m.value for m in enum_cls]}, got {value!r}"
    )


def assert_admission_cycle(data: dict):
    _assert_common_fields(data, "AdmissionCycle")
    assert isinstance(data["academic_year"], str) and data["academic_year"]
    for field in ("early_deadline_at", "regular_deadline_at",
                  "reenroll_response_deadline_at", "melt_deadline_at"):
        assert is_iso8601_timestamp(data[field]), (
            f"AdmissionCycle.{field} must be ISO 8601 UTC"
        )
    assert isinstance(data["aid_budget_total_cents"], int)
    assert data["aid_budget_total_cents"] >= 0
    assert isinstance(data["aid_committed_cents"], int)
    assert isinstance(data["pacing_cap_cents"], int)
    _assert_enum(data["status"], CycleStatus, "AdmissionCycle.status")


def assert_grade_section(data: dict):
    _assert_common_fields(data, "GradeSection")
    assert is_valid_uuid(data["cycle_id"]), "GradeSection.cycle_id must be a UUID"
    _assert_enum(data["grade_level"], GradeLevel, "GradeSection.grade_level")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["tuition_cents"], int) and data["tuition_cents"] >= 0
    assert isinstance(data["max_aid_seat_pct"], (int, float))
    assert 0 <= data["max_aid_seat_pct"] <= 1
    assert isinstance(data["seats_held"], int) and data["seats_held"] >= 0
    assert isinstance(data["aid_seats_held"], int) and data["aid_seats_held"] >= 0
    assert isinstance(data["seats_available"], int)


def assert_applicant(data: dict):
    _assert_common_fields(data, "Applicant")
    assert isinstance(data["family_id"], str) and data["family_id"]
    assert isinstance(data["first_name"], str) and data["first_name"]
    assert isinstance(data["last_name"], str) and data["last_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["legacy_parent"], bool)


def assert_student(data: dict):
    _assert_common_fields(data, "Student")
    assert isinstance(data["family_id"], str) and data["family_id"]
    assert isinstance(data["first_name"], str) and data["first_name"]
    assert isinstance(data["last_name"], str) and data["last_name"]
    assert is_valid_uuid(data["current_grade_section_id"])
    _assert_enum(data["status"], StudentStatus, "Student.status")
    _assert_enum(data["source"], StudentSource, "Student.source")
    assert data.get("re_enrolled_for_cycle_id") is None or is_valid_uuid(
        data["re_enrolled_for_cycle_id"]
    )


def assert_application(data: dict):
    _assert_common_fields(data, "Application")
    for field in ("applicant_id", "cycle_id", "grade_section_id"):
        assert is_valid_uuid(data[field]), f"Application.{field} must be a UUID"
    _assert_enum(data["round"], ApplicationRound, "Application.round")
    _assert_enum(data["status"], ApplicationStatus, "Application.status")
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])
    assert data.get("composite_score") is None or isinstance(
        data["composite_score"], (int, float)
    )
    assert isinstance(data["preference_points"], int)
    assert isinstance(data["sibling_verified"], bool)
    assert data.get("offer_expires_at") is None or is_iso8601_timestamp(
        data["offer_expires_at"]
    )
    assert isinstance(data["promoted_from_waitlist"], bool)
    assert data.get("estimated_deposit_cents") is None or isinstance(
        data["estimated_deposit_cents"], int
    )


def assert_entrance_evaluation(data: dict):
    _assert_common_fields(data, "EntranceEvaluation")
    assert is_valid_uuid(data["application_id"])
    _assert_enum(data["kind"], EvaluationKind, "EntranceEvaluation.kind")
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    _assert_enum(data["status"], EvaluationStatus, "EntranceEvaluation.status")
    assert data.get("score") is None or isinstance(data["score"], int)


def assert_test_session(data: dict):
    _assert_common_fields(data, "TestSession")
    assert is_valid_uuid(data["cycle_id"])
    assert is_iso8601_timestamp(data["session_start"])
    assert is_iso8601_timestamp(data["session_end"])
    assert isinstance(data["room_capacity"], int) and data["room_capacity"] >= 1
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0


def assert_aid_application(data: dict):
    _assert_common_fields(data, "AidApplication")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["reported_annual_income_cents"], int)
    assert data["reported_annual_income_cents"] >= 0
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert data.get("verified_annual_income_cents") is None or isinstance(
        data["verified_annual_income_cents"], int
    )
    assert data.get("verified_by_user_id") is None or isinstance(
        data["verified_by_user_id"], str
    )
    _assert_enum(
        data["verification_status"], VerificationStatus,
        "AidApplication.verification_status",
    )
    assert isinstance(data["provisional_award_cents"], int)
    assert data.get("final_award_cents") is None or isinstance(
        data["final_award_cents"], int
    )
    _assert_enum(data["award_status"], AwardStatus, "AidApplication.award_status")
    assert data.get("appeal_reason") is None or isinstance(data["appeal_reason"], str)


def assert_enrollment_contract(data: dict):
    _assert_common_fields(data, "EnrollmentContract")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["tuition_cents"], int)
    assert isinstance(data["award_cents"], int)
    assert isinstance(data["net_tuition_cents"], int)
    assert isinstance(data["deposit_amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert is_iso8601_timestamp(data["response_due_at"])
    assert data.get("created_student_id") is None or is_valid_uuid(
        data["created_student_id"]
    )
    _assert_enum(data["status"], ContractStatus, "EnrollmentContract.status")


def assert_reenrollment_offer(data: dict):
    _assert_common_fields(data, "ReenrollmentOffer")
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["cycle_id"])
    assert isinstance(data["prior_tuition_cents"], int)
    assert isinstance(data["new_tuition_cents"], int)
    assert isinstance(data["sibling_discount_cents"], int)
    assert isinstance(data["discounted_tuition_cents"], int)
    assert is_iso8601_timestamp(data["response_deadline_at"])
    _assert_enum(data["status"], ReenrollmentOfferStatus, "ReenrollmentOffer.status")


def assert_sweep_result(data: dict):
    """The run-sweep inline summary object (PRD §3.5)."""
    for field in ("expired_offer_count", "lapsed_contract_count",
                  "expired_waitlist_count", "lapsed_reenrollment_count"):
        assert isinstance(data.get(field), int) and data[field] >= 0, (
            f"sweep result {field} must be a non-negative integer"
        )
    assert isinstance(data.get("promoted_application_ids"), list), (
        "sweep result promoted_application_ids must be a list"
    )


def assert_seat_ledger(section: dict):
    """PRD §2.9 seat-ledger invariant on a GradeSection payload."""
    assert section["seats_held"] >= 0
    assert 0 <= section["aid_seats_held"] <= section["seats_held"]
    assert section["seats_available"] == section["capacity"] - section["seats_held"]
    assert section["seats_available"] >= 0
