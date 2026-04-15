"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_semester(data: dict):
    """Assert all expected fields on a Semester entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["term_label"], str) and len(data["term_label"]) > 0, "term_label required"
    assert isinstance(data["year"], int), "year must be integer"
    assert isinstance(data["registration_opens"], str), "registration_opens required"
    assert isinstance(data["registration_closes"], str), "registration_closes required"
    assert isinstance(data["late_drop_deadline"], str), "late_drop_deadline required"
    assert data["phase"] in ["PLANNING", "OPEN_ENROLLMENT", "CLOSED_ENROLLMENT", "FINALIZED"], \
        f"Invalid phase: {data['phase']}"
    assert is_iso8601_timestamp(data.get("opened_on", "")), "opened_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("modified_on", "")), "modified_on must be ISO 8601"


def assert_department(data: dict):
    """Assert all expected fields on a Department entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("semester_id", "")), "semester_id must be valid UUID"
    assert isinstance(data["dept_code"], str) and len(data["dept_code"]) > 0, "dept_code required"
    assert isinstance(data["dept_name"], str) and len(data["dept_name"]) > 0, "dept_name required"
    assert isinstance(data["cross_dept_open"], bool), "cross_dept_open must be boolean"
    assert is_iso8601_timestamp(data.get("opened_on", "")), "opened_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("modified_on", "")), "modified_on must be ISO 8601"


def assert_course(data: dict):
    """Assert all expected fields on a Course entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("department_id", "")), "department_id must be valid UUID"
    assert isinstance(data["course_code"], str) and len(data["course_code"]) > 0, "course_code required"
    assert isinstance(data["title"], str) and len(data["title"]) > 0, "title required"
    assert isinstance(data["credit_hours"], int) and data["credit_hours"] > 0, "credit_hours must be positive int"
    assert data["level"] in ["INTRODUCTORY", "INTERMEDIATE", "ADVANCED", "GRADUATE"], \
        f"Invalid level: {data['level']}"
    assert isinstance(data.get("min_gpa", 0), (int, float)), "min_gpa must be numeric"
    assert isinstance(data.get("prerequisite_ids", []), list), "prerequisite_ids must be list"
    assert isinstance(data.get("corequisite_ids", []), list), "corequisite_ids must be list"
    assert isinstance(data["is_active"], bool), "is_active must be boolean"
    assert is_iso8601_timestamp(data.get("opened_on", "")), "opened_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("modified_on", "")), "modified_on must be ISO 8601"


def assert_section(data: dict):
    """Assert all expected fields on a Section entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("course_id", "")), "course_id must be valid UUID"
    assert isinstance(data["section_number"], str), "section_number required"
    assert is_valid_uuid(data.get("instructor_id", "")), "instructor_id must be valid UUID"
    assert isinstance(data["capacity"], int) and data["capacity"] > 0, "capacity must be positive int"
    assert isinstance(data["waitlist_cap"], int), "waitlist_cap must be int"
    assert isinstance(data["schedule_days"], str), "schedule_days required"
    assert isinstance(data["schedule_start"], str), "schedule_start required"
    assert isinstance(data["schedule_end"], str), "schedule_end required"
    assert isinstance(data["location"], str), "location required"
    assert isinstance(data["seats_enrolled"], int), "seats_enrolled must be int"
    assert isinstance(data["seats_available"], int), "seats_available must be int"
    assert isinstance(data["waitlist_count"], int), "waitlist_count must be int"
    assert isinstance(data["requires_approval"], bool), "requires_approval must be boolean"
    assert isinstance(data["enrollment_seq"], int), "enrollment_seq must be int"
    assert is_iso8601_timestamp(data.get("opened_on", "")), "opened_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("modified_on", "")), "modified_on must be ISO 8601"
    # Derived field invariants
    assert data["seats_available"] == data["capacity"] - data["seats_enrolled"], \
        f"seats_available ({data['seats_available']}) != capacity ({data['capacity']}) - seats_enrolled ({data['seats_enrolled']})"
    assert data["seats_enrolled"] >= 0, "seats_enrolled must be >= 0"
    assert data["seats_available"] >= 0, "seats_available must be >= 0"
    assert data["waitlist_count"] >= 0, "waitlist_count must be >= 0"


def assert_instructor(data: dict):
    """Assert all expected fields on an Instructor entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("semester_id", "")), "semester_id must be valid UUID"
    assert isinstance(data["employee_number"], str) and len(data["employee_number"]) > 0, "employee_number required"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0, "full_name required"
    assert is_valid_uuid(data.get("home_department_id", "")), "home_department_id must be valid UUID"
    assert isinstance(data["can_approve_cross_dept"], bool), "can_approve_cross_dept must be boolean"
    assert is_iso8601_timestamp(data.get("opened_on", "")), "opened_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("modified_on", "")), "modified_on must be ISO 8601"


def assert_student(data: dict):
    """Assert all expected fields on a Student entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("semester_id", "")), "semester_id must be valid UUID"
    assert isinstance(data["student_number"], str) and len(data["student_number"]) > 0, "student_number required"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0, "full_name required"
    assert is_valid_uuid(data.get("major_department_id", "")), "major_department_id must be valid UUID"
    assert data["academic_standing"] in ["GOOD", "PROBATION", "SUSPENDED"], \
        f"Invalid academic_standing: {data['academic_standing']}"
    assert isinstance(data["cumulative_gpa"], (int, float)), "cumulative_gpa must be numeric"
    assert isinstance(data["max_credits"], int), "max_credits must be int"
    assert isinstance(data["credits_enrolled"], int), "credits_enrolled must be int"
    assert isinstance(data["credits_available"], int), "credits_available must be int"
    assert isinstance(data.get("completed_course_ids", []), list), "completed_course_ids must be list"
    assert is_iso8601_timestamp(data.get("opened_on", "")), "opened_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("modified_on", "")), "modified_on must be ISO 8601"
    # Derived field invariant
    assert data["credits_available"] == data["max_credits"] - data["credits_enrolled"], \
        f"credits_available ({data['credits_available']}) != max_credits ({data['max_credits']}) - credits_enrolled ({data['credits_enrolled']})"


def assert_enrollment(data: dict):
    """Assert all expected fields on an Enrollment entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("section_id", "")), "section_id must be valid UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be valid UUID"
    assert data["status"] in [
        "PENDING_APPROVAL", "ENROLLED", "WAITLISTED", "DROPPED", "WITHDRAWN", "REJECTED"
    ], f"Invalid enrollment status: {data['status']}"
    assert isinstance(data["is_cross_dept"], bool), "is_cross_dept must be boolean"
    assert isinstance(data["enrollment_seq"], int), "enrollment_seq must be int"
    assert is_iso8601_timestamp(data.get("opened_on", "")), "opened_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("modified_on", "")), "modified_on must be ISO 8601"


def assert_cross_dept_permission(data: dict):
    """Assert all expected fields on a CrossDeptPermission entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("semester_id", "")), "semester_id must be valid UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be valid UUID"
    assert is_valid_uuid(data.get("target_department_id", "")), "target_department_id must be valid UUID"
    assert isinstance(data["max_courses"], int), "max_courses must be int"
    assert isinstance(data["courses_used"], int), "courses_used must be int"
    assert data["status"] in ["ACTIVE", "REVOKED"], f"Invalid permission status: {data['status']}"
    assert is_iso8601_timestamp(data.get("opened_on", "")), "opened_on must be ISO 8601"
    assert is_iso8601_timestamp(data.get("modified_on", "")), "modified_on must be ISO 8601"


def assert_schedule_conflict(data: dict):
    """Assert all expected fields on a ScheduleConflict record."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be valid UUID"
    assert is_valid_uuid(data.get("section_a_id", "")), "section_a_id must be valid UUID"
    assert is_valid_uuid(data.get("section_b_id", "")), "section_b_id must be valid UUID"
    assert isinstance(data["overlap_days"], str), "overlap_days must be string"
    assert isinstance(data["overlap_minutes"], int) and data["overlap_minutes"] > 0, "overlap_minutes must be positive int"
    assert isinstance(data["detected_on"], str), "detected_on must be string"


def assert_waitlist_promotion(data: dict):
    """Assert all expected fields on a WaitlistPromotion record."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be valid UUID"
    assert is_valid_uuid(data.get("section_id", "")), "section_id must be valid UUID"
    assert isinstance(data["previous_position"], int) and data["previous_position"] >= 1, \
        "previous_position must be >= 1"
    assert isinstance(data["trigger_event"], str), "trigger_event must be string"
    assert isinstance(data["promoted_on"], str), "promoted_on must be string"


def assert_prerequisite_graph(data: dict):
    """Assert all expected fields on a PrerequisiteGraph record."""
    assert is_valid_uuid(data.get("course_id", "")), "course_id must be valid UUID"
    assert isinstance(data["dependency_chain"], list), "dependency_chain must be list"
    assert isinstance(data["depth"], int) and data["depth"] >= 0, "depth must be non-negative int"
    assert isinstance(data["has_cycle"], bool), "has_cycle must be boolean"
