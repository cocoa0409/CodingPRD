"""Entity assertions for the Driving School API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_student(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"Student.id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Student.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "Student.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["enrollment_status"] in [
        "PENDING_VERIFICATION", "PENDING_MEDICAL", "PENDING_PACKAGE",
        "PENDING_CONTRACT", "ACTIVE", "SUSPENDED", "COMPLETED",
    ]
    assert data["training_stage"] in ["THEORY", "BASIC", "HIGHWAY", "COMPLETED"]
    assert data["medical_cert_status"] in ["PENDING", "VALID", "EXPIRED"]
    assert isinstance(data["id_verified"], bool)
    assert isinstance(data["no_show_count_this_cycle"], int)
    assert isinstance(data["reschedule_count_this_cycle"], int)
    assert isinstance(data["has_passed_theory"], bool)
    assert isinstance(data["has_passed_basic_practical"], bool)


def assert_instructor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Instructor.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["full_name"], str)
    assert isinstance(data["license_number"], str)
    assert isinstance(data["vehicle_qualifications"], list)
    for vt in data["vehicle_qualifications"]:
        assert vt in ["MANUAL_C1", "AUTO_C2", "TRUCK_B2", "MOTORCYCLE_E"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_vehicle(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data["plate_number"], str)
    assert data["vehicle_type"] in ["MANUAL_C1", "AUTO_C2", "TRUCK_B2", "MOTORCYCLE_E"]
    assert data["status"] in ["ACTIVE", "MAINTENANCE", "RETIRED"]


def assert_course_package(data: dict):
    """CoursePackage is common_fields=false — only id + created_at."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["name"], str)
    assert isinstance(data["total_minutes"], int)
    assert isinstance(data["total_price_cents"], int)
    assert isinstance(data["included_simulator_sessions"], int)
    assert isinstance(data["included_exam_attempts"], int)
    assert isinstance(data["per_minute_overage_price_cents"], int)
    assert isinstance(data["per_simulator_session_overage_price_cents"], int)


def assert_practice(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["instructor_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["vehicle_type"] in ["MANUAL_C1", "AUTO_C2", "TRUCK_B2", "MOTORCYCLE_E"]
    assert data["training_stage"] in ["THEORY", "BASIC", "HIGHWAY"]
    assert data["status"] in ["BOOKED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW"]
    assert isinstance(data["scheduled_minutes"], int) and data["scheduled_minutes"] >= 0


def assert_exam(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data["student_id"])
    assert data["exam_type"] in ["THEORY_TEST", "BASIC_TEST", "FINAL_TEST"]
    assert data["status"] in ["BOOKED", "PASSED", "FAILED", "CANCELLED", "NO_SHOW"]
    assert isinstance(data["passing_score"], int)
    assert isinstance(data["retake_index"], int) and data["retake_index"] >= 1
    assert data["prerequisite_stage"] in ["THEORY", "BASIC", "HIGHWAY"]


def assert_simulator(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data["student_id"])
    assert data["status"] in ["BOOKED", "COMPLETED", "CANCELLED", "NO_SHOW"]
    assert isinstance(data["charged_to_package"], bool)
    assert isinstance(data["overage_cents"], int) and data["overage_cents"] >= 0


def assert_complaint(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data["student_id"])
    assert data["category"] in ["SCHEDULING", "INSTRUCTOR_CONDUCT", "BILLING", "FACILITY", "OTHER"]
    assert isinstance(data["level"], int) and 1 <= data["level"] <= 3
    assert data["status"] in ["OPEN", "IN_REVIEW", "ESCALATED", "RESOLVED", "REJECTED"]


def assert_training_hour_record(data: dict):
    """TrainingHourRecord is append-only — id + created_at only."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["source_appointment_id"])
    assert data["training_stage"] in ["THEORY", "BASIC", "HIGHWAY"]
    assert isinstance(data["minutes_recorded"], int) and data["minutes_recorded"] >= 0
    assert isinstance(data["gps_validated"], bool)
    assert data["authority_submission_status"] in ["PENDING", "SUBMITTED"]


def assert_audit_log(data: dict):
    """AuditLog is append-only — id + created_at only."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_id"], str)
    assert isinstance(data["entity_type"], str)
    assert isinstance(data["entity_id"], str)
    assert data["action"] in [
        "CREATE", "UPDATE", "CANCEL", "CHECK_IN", "CHECK_OUT", "RESCHEDULE",
        "RECORD_RESULT", "SUBMIT_HOURS", "NO_SHOW_SWEEP", "ESCALATE", "RESOLVE",
        "REJECT", "ASSIGN_HANDLER",
    ]
