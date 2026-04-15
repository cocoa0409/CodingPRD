"""Payload factories from scaffold Table 1 input fields."""
import uuid


def _unique_suffix():
    return uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Semester
# ---------------------------------------------------------------------------
def create_semester_payload(**overrides) -> dict:
    defaults = {
        "term_label": f"Fall {_unique_suffix()}",
        "year": 2026,
        "registration_opens": "2026-08-01T00:00:00Z",
        "registration_closes": "2026-09-15T23:59:59Z",
        "late_drop_deadline": "2026-10-15T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------
def create_department_payload(**overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "dept_code": f"D{suffix[:4].upper()}",
        "dept_name": f"Department {suffix}",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------
def create_course_payload(**overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "course_code": f"C-{suffix[:4].upper()}",
        "title": f"Course {suffix}",
        "credit_hours": 3,
        "level": "INTERMEDIATE",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------
def create_section_payload(instructor_id, **overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "section_number": f"S{suffix[:3]}",
        "instructor_id": instructor_id,
        "capacity": 30,
        "schedule_days": "MWF",
        "schedule_start": "09:00",
        "schedule_end": "10:00",
        "location": "Room-101",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Instructor
# ---------------------------------------------------------------------------
def create_instructor_payload(home_department_id, **overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "employee_number": f"EMP-{suffix}",
        "full_name": f"Prof {suffix}",
        "home_department_id": home_department_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------
def create_student_payload(major_department_id, **overrides) -> dict:
    suffix = _unique_suffix()
    defaults = {
        "student_number": f"STU-{suffix}",
        "full_name": f"Student {suffix}",
        "major_department_id": major_department_id,
        "cumulative_gpa": 3.5,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------
def create_enrollment_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# CrossDeptPermission
# ---------------------------------------------------------------------------
def create_cross_dept_permission_payload(student_id, target_department_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "target_department_id": target_department_id,
    }
    defaults.update(overrides)
    return defaults
