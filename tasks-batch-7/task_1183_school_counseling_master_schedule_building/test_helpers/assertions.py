"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

from .types import (
    TermPosture, SpecialProgram, RoomType, SubjectArea, CourseRequestState,
    SectionState, ScheduleEntryState, ScheduleEntryOrigin, ChangeRequestKind,
    ChangeRequestState, AppointmentState, RecoveryPlacementState,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_slim_common(data: dict):
    """For append-only resources carrying only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only resource must not expose updated_at"
    assert "version" not in data, "append-only resource must not expose version"


def assert_term(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["posture"] in [p.value for p in TermPosture]
    assert isinstance(data["periods_per_day"], int)
    assert 4 <= data["periods_per_day"] <= 10
    assert isinstance(data["max_students_per_section"], int)
    assert 1 <= data["max_students_per_section"] <= 40
    assert isinstance(data["class_size_target"], int)
    assert 1 <= data["class_size_target"] < data["max_students_per_section"]
    assert isinstance(data["singleton_section_cap"], int)
    assert data["singleton_section_cap"] >= 0
    assert isinstance(data["change_window_open"], bool)
    assert isinstance(data["change_request_max_per_student"], int)
    assert data["change_request_max_per_student"] >= 1
    assert isinstance(data["rebalance_epoch"], int)
    assert isinstance(data["total_requested_seats"], int)


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["external_ref"], str) and 4 <= len(data["external_ref"]) <= 32
    assert isinstance(data["full_name"], str)
    assert data["grade_level"] in (9, 10, 11, 12)
    assert data["special_program"] in [p.value for p in SpecialProgram]
    assert is_valid_uuid(data.get("counselor_id", ""))
    assert isinstance(data["earned_credits"], (int, float))
    assert data["earned_credits"] >= 0
    assert isinstance(data["planned_credit_load"], (int, float))
    assert isinstance(data["credit_deficient"], bool)


def assert_counselor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["max_caseload"], int) and data["max_caseload"] >= 1
    assert isinstance(data["caseload_count"], int) and data["caseload_count"] >= 0


def assert_teacher(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["max_sections"], int) and data["max_sections"] >= 1
    assert isinstance(data["assigned_section_count"], int) and data["assigned_section_count"] >= 0


def assert_teacher_qualification(data: dict):
    _assert_slim_common(data)
    assert is_valid_uuid(data.get("teacher_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert is_iso8601_timestamp(data.get("qualified_at", ""))


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["room_number"], str) and len(data["room_number"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["room_type"] in [r.value for r in RoomType]


def assert_course(data: dict):
    _assert_common(data)
    assert isinstance(data["course_code"], str) and len(data["course_code"]) > 0
    assert isinstance(data["title"], str)
    credits = data["credits"]
    assert isinstance(credits, (int, float))
    assert 0.25 <= float(credits) <= 2.00
    assert abs(float(credits) * 4 - round(float(credits) * 4)) < 1e-9, "credits must be a 0.25 step"
    assert data["subject_area"] in [s.value for s in SubjectArea]
    assert data["required_room_type"] in [r.value for r in RoomType]
    assert isinstance(data["singleton"], bool)
    assert isinstance(data["grade_band_min"], int) and 9 <= data["grade_band_min"] <= 12
    assert isinstance(data["grade_band_max"], int)
    assert data["grade_band_min"] <= data["grade_band_max"] <= 12
    assert data["special_program_exclusive"] in [p.value for p in SpecialProgram]
    assert data.get("prerequisite_course_id") is None or is_valid_uuid(data["prerequisite_course_id"])


def assert_course_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1
    assert isinstance(data["is_alternate"], bool)
    assert data["state"] in [s.value for s in CourseRequestState]
    assert isinstance(data["tally_weight"], (int, float))


def assert_section(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("term_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert data.get("teacher_id") is None or is_valid_uuid(data["teacher_id"])
    assert data.get("room_id") is None or is_valid_uuid(data["room_id"])
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["cohort_counts"], dict)
    assert data["state"] in [s.value for s in SectionState]
    assert isinstance(data["under_enrolled"], bool)


def assert_schedule_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("section_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    assert data["state"] in [s.value for s in ScheduleEntryState]
    assert data["origin"] in [o.value for o in ScheduleEntryOrigin]
    assert data.get("moved_to_section_id") is None or is_valid_uuid(data["moved_to_section_id"])
    assert isinstance(data["epoch_placed"], int)


def assert_change_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    assert data["kind"] in [k.value for k in ChangeRequestKind]
    assert data.get("drop_entry_id") is None or is_valid_uuid(data["drop_entry_id"])
    assert data.get("add_section_id") is None or is_valid_uuid(data["add_section_id"])
    assert isinstance(data["reason"], str) and 10 <= len(data["reason"]) <= 500
    assert data["state"] in [s.value for s in ChangeRequestState]
    assert data.get("reviewed_by_counselor_id") is None or is_valid_uuid(data["reviewed_by_counselor_id"])
    assert isinstance(data["decided_by_admin"], bool)


def assert_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("counselor_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert data["state"] in [s.value for s in AppointmentState]
    assert isinstance(data["no_show_count_snapshot"], int)


def assert_credit_audit(data: dict):
    _assert_slim_common(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    assert isinstance(data["required_credits"], (int, float))
    assert isinstance(data["projected_credits"], (int, float))
    assert isinstance(data["deficiency_credits"], (int, float))
    assert isinstance(data["deficient_subjects"], list)
    assert isinstance(data["audit_epoch"], int)


def assert_recovery_placement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    assert is_valid_uuid(data.get("target_course_id", ""))
    assert data.get("section_id") is None or is_valid_uuid(data["section_id"])
    assert data["state"] in [s.value for s in RecoveryPlacementState]
    assert isinstance(data["priority_score"], (int, float))


def assert_rebalance_run(data: dict):
    _assert_slim_common(data)
    assert is_valid_uuid(data.get("term_id", ""))
    assert isinstance(data["epoch"], int)
    assert isinstance(data["moves_proposed"], int)
    assert isinstance(data["imbalance_score_before"], (int, float))
    assert isinstance(data["imbalance_score_after"], (int, float))
    assert is_iso8601_timestamp(data.get("executed_at", ""))
