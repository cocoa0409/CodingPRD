"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_center(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["territory_code"], str) and len(data["territory_code"]) > 0
    assert isinstance(data["instructor_ratio_cap"], int) and data["instructor_ratio_cap"] >= 1
    assert isinstance(data["enrollment_fee_cents"], int) and data["enrollment_fee_cents"] >= 0
    assert isinstance(data["monthly_tuition_cents"], int) and data["monthly_tuition_cents"] >= 0
    assert data["status"] in ("PROVISIONING", "OPERATING", "SUSPENDED")
    assert isinstance(data["active_enrollment_count"], int) and data["active_enrollment_count"] >= 0


def assert_agreement(data: dict):
    _common(data)
    assert isinstance(data["center_id"], str)
    assert 0 <= data["royalty_rate_bps"] <= 10000
    assert 0 <= data["marketing_fee_bps"] <= 10000
    assert data["minimum_monthly_royalty_cents"] >= 0
    assert data["royalty_basis"] in ("ROYALTY_FLOOR", "COMBINED_FLOOR")
    assert data["status"] in ("PENDING", "ACTIVE", "TERMINATED")


def assert_subject(data: dict):
    _common(data)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["status"] == "ACTIVE"


def assert_curriculum_level(data: dict):
    _common(data)
    assert isinstance(data["subject_id"], str)
    assert isinstance(data["rank"], int) and data["rank"] >= 1
    assert isinstance(data["label"], str)
    assert isinstance(data["worksheets_to_master"], int) and data["worksheets_to_master"] >= 1
    assert 0 <= data["mastery_score_threshold"] <= 100


def assert_family(data: dict):
    _common(data)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["contact_name"], str)
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["sibling_count"], int) and data["sibling_count"] >= 0


def assert_student(data: dict):
    _common(data)
    assert isinstance(data["family_id"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["enrollment_fee_charged"], bool)


def assert_enrollment(data: dict):
    _common(data)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["subject_id"], str)
    assert data["status"] in (
        "PLACEMENT_PENDING", "ACTIVE", "PAUSED", "COMPLETED", "WITHDRAWN",
    )
    assert isinstance(data["mastered_sets_in_level"], int) and data["mastered_sets_in_level"] >= 0
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] >= 0


def assert_worksheet(data: dict):
    _common(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["level_id"], str)
    assert isinstance(data["set_number"], int) and data["set_number"] >= 1
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert data["status"] in ("ASSIGNED", "GRADED", "RETRY", "MASTERED")


def assert_session(data: dict):
    _common(data)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["instructor_user_id"], str)
    assert isinstance(data["seat_cap"], int) and data["seat_cap"] >= 1
    assert isinstance(data["booked_seat_count"], int) and data["booked_seat_count"] >= 0
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED", "CANCELLED")


def assert_attendance_record(data: dict):
    _common(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["enrollment_id"], str)
    assert data["status"] in ("BOOKED", "PRESENT", "ABSENT", "CANCELLED")


def assert_invoice(data: dict):
    _common(data)
    assert isinstance(data["family_id"], str)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["period_month"], str)
    assert data["enrollment_fee_component_cents"] >= 0
    assert data["tuition_component_cents"] >= 0
    assert data["wallet_applied_cents"] >= 0
    assert data["total_due_cents"] >= 0
    assert data["royalty_owed_cents"] >= 0
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")
