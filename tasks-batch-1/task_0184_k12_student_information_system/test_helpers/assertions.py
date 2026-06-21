"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Per PRD §2.6 every entity carries id/created_at/
updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_school(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["ada_method"] in ("AGGREGATE_MEMBERSHIP", "DAYS_PRESENT")
    assert isinstance(data["minimum_daily_minutes"], int)
    assert isinstance(data["current_school_day_index"], int)
    assert isinstance(data["session_total_days"], int)


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["school_id"], str)
    assert isinstance(data["state_student_id"], str)
    assert isinstance(data["first_name"], str)
    assert isinstance(data["last_name"], str)
    assert data["grade_level"] in ("K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12")
    assert data["status"] in ("PROSPECTIVE", "ENROLLED", "WITHDRAWN")


def assert_enrollment(data: dict):
    _assert_common(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["school_id"], str)
    assert isinstance(data["entry_day_index"], int)
    assert isinstance(data["fte"], (int, float))
    assert 0 < float(data["fte"]) <= 1.0
    assert isinstance(data["membership_days"], int)
    assert isinstance(data["present_days"], int)
    assert data["status"] in ("ACTIVE", "WITHDRAWN", "NO_SHOW")


def assert_course(data: dict):
    _assert_common(data)
    assert isinstance(data["school_id"], str)
    assert isinstance(data["course_code"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["credit_value"], (int, float))
    assert data["grading_mode"] in ("STANDARDS", "TRADITIONAL")


def assert_section(data: dict):
    _assert_common(data)
    assert isinstance(data["course_id"], str)
    assert isinstance(data["school_id"], str)
    assert isinstance(data["teacher_user_id"], str)
    assert isinstance(data["period"], int) and 1 <= data["period"] <= 8
    assert isinstance(data["meeting_minutes"], int)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["enrolled_count"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_schedule_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["section_id"], str)
    assert isinstance(data["period"], int)
    assert data["status"] in ("ENROLLED", "DROPPED")


def assert_attendance_record(data: dict):
    _assert_common(data)
    assert isinstance(data["schedule_assignment_id"], str)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["day_index"], int)
    assert data["code"] in ("PRESENT", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED", "TARDY")
    assert data["source"] in ("TEACHER", "SYSTEM_SUSPENSION")
    assert isinstance(data["present_minutes"], int)
    assert data["status"] in ("RECORDED", "SUPERSEDED")


def assert_daily_attendance(data: dict):
    _assert_common(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["day_index"], int)
    assert isinstance(data["present_minutes_total"], int)
    assert data["daily_code"] in ("PRESENT", "PARTIAL", "ABSENT")
    assert isinstance(data["ada_eligible"], bool)


def assert_standard_score(data: dict):
    _assert_common(data)
    assert isinstance(data["schedule_assignment_id"], str)
    assert isinstance(data["section_id"], str)
    assert isinstance(data["standard_code"], str)


def assert_report_card(data: dict):
    _assert_common(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["term_label"], str)
    assert data["status"] in ("DRAFT", "FINALIZED", "REOPENED")


def assert_discipline_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["enrollment_id"], str)
    assert data["category"] in ("DISRUPTION", "FIGHTING", "TRUANCY", "ACADEMIC_DISHONESTY", "WEAPON")
    assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 5
    assert isinstance(data["incident_day_index"], int)
    assert data["status"] in ("REFERRED", "UNDER_REVIEW", "ADJUDICATED", "DISMISSED")


def assert_discipline_consequence(data: dict):
    _assert_common(data)
    assert isinstance(data["incident_id"], str)
    assert isinstance(data["enrollment_id"], str)
    assert data["type"] in ("WARNING", "DETENTION", "IN_SCHOOL_SUSPENSION", "OUT_OF_SCHOOL_SUSPENSION")
    assert data["status"] in ("ACTIVE", "RESCINDED")


def assert_ada_funding_report(data: dict):
    _assert_common(data)
    assert isinstance(data["school_id"], str)
    assert isinstance(data["as_of_day_index"], int)
    assert data["method_used"] in ("AGGREGATE_MEMBERSHIP", "DAYS_PRESENT")
    assert isinstance(data["total_ada"], (int, float))
    assert isinstance(data["funded_enrollment_count"], int)
    assert data["status"] in ("DRAFT", "CERTIFIED", "REJECTED")


def find_line_item(report_card: dict, section_id: str) -> dict:
    """Return the report card line item whose section_id matches, or fail."""
    items = report_card.get("line_items") or []
    for item in items:
        if item.get("section_id") == section_id:
            return item
    raise AssertionError(
        f"no line_item for section_id={section_id}; line_items={items!r}"
    )
