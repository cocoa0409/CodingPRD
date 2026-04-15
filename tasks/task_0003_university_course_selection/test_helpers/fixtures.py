"""Composite setup helpers — tiers 1-6 for the Course Selection domain.

Every fixture uses get_success_data() (lenient validator) internally so setup
failures produce clear error messages rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data, validate_success, build_user_headers

from .api_client import api_client
from .factories import (
    create_semester_payload,
    create_department_payload,
    create_course_payload,
    create_section_payload,
    create_instructor_payload,
    create_student_payload,
    create_enrollment_payload,
    create_cross_dept_permission_payload,
)

# Default registrar headers for fixture setup calls
_REG = build_user_headers("fixture-registrar", "Registrar")
_PROF = build_user_headers("fixture-professor", "Professor")
_STU = build_user_headers("fixture-student", "Student")


# =============================================================================
# Tier 1: State Progression — Semester phase transitions
# =============================================================================

def create_semester(**overrides):
    """Create a semester in PLANNING phase. Returns semester dict."""
    payload = create_semester_payload(**overrides)
    resp = api_client.create_semester(payload, _REG)
    return get_success_data(resp)


def create_semester_in_open_enrollment(**overrides):
    """Create a semester and transition it to OPEN_ENROLLMENT.
    Requires at least one department, course, and section to exist.
    Returns (semester, department, course, section, instructor).
    """
    semester = create_semester(**overrides)
    sid = semester["id"]

    dept = create_department(sid)
    instructor = create_instructor(sid, dept["id"])
    course = create_course(sid, dept["id"])
    section = create_section(sid, dept["id"], course["id"], instructor["id"])

    resp = api_client.open_enrollment(sid, _REG)
    semester = get_success_data(resp)
    return semester, dept, course, section, instructor


def create_semester_in_closed_enrollment(**overrides):
    """Create a semester and transition it to CLOSED_ENROLLMENT.
    Returns (semester, department, course, section, instructor).
    """
    semester, dept, course, section, instructor = create_semester_in_open_enrollment(**overrides)
    sid = semester["id"]
    resp = api_client.close_enrollment(sid, _REG)
    semester = get_success_data(resp)
    return semester, dept, course, section, instructor


# =============================================================================
# Tier 2: Entity Hierarchy — Basic entity creation helpers
# =============================================================================

def create_department(semester_id, **overrides):
    """Create a department in the given semester. Returns department dict."""
    payload = create_department_payload(**overrides)
    resp = api_client.create_department(semester_id, payload, _REG)
    return get_success_data(resp)


def create_instructor(semester_id, department_id, **overrides):
    """Create an instructor. Returns instructor dict."""
    payload = create_instructor_payload(department_id, **overrides)
    resp = api_client.create_instructor(semester_id, payload, _REG)
    return get_success_data(resp)


def create_course(semester_id, department_id, **overrides):
    """Create a course in the given department. Returns course dict."""
    payload = create_course_payload(**overrides)
    resp = api_client.create_course(semester_id, department_id, payload, _REG)
    return get_success_data(resp)


def create_section(semester_id, department_id, course_id, instructor_id, **overrides):
    """Create a section for a course. Returns section dict."""
    payload = create_section_payload(instructor_id, **overrides)
    resp = api_client.create_section(semester_id, department_id, course_id, payload, _REG)
    return get_success_data(resp)


def create_student(semester_id, major_department_id, **overrides):
    """Create a student. Returns student dict."""
    payload = create_student_payload(major_department_id, **overrides)
    resp = api_client.create_student(semester_id, payload, _REG)
    return get_success_data(resp)


def create_cross_dept_permission(semester_id, student_id, target_department_id, **overrides):
    """Grant a cross-dept permission. Returns permission dict."""
    payload = create_cross_dept_permission_payload(student_id, target_department_id, **overrides)
    resp = api_client.create_cross_dept_permission(semester_id, payload, _REG)
    return get_success_data(resp)


# =============================================================================
# Tier 2 continued: Full scenario setups
# =============================================================================

def setup_open_semester_with_student(**overrides):
    """Create open-enrollment semester + one student in the same department.
    Returns (semester, dept, course, section, instructor, student).
    """
    semester, dept, course, section, instructor = create_semester_in_open_enrollment(**overrides)
    sid = semester["id"]
    student = create_student(sid, dept["id"])
    return semester, dept, course, section, instructor, student


def setup_enrollment_ready(**overrides):
    """Create open-enrollment semester + student, ready for enrollment.
    Returns dict with all entity IDs and objects for convenience.
    """
    semester, dept, course, section, instructor, student = setup_open_semester_with_student(**overrides)
    return {
        "semester": semester,
        "department": dept,
        "course": course,
        "section": section,
        "instructor": instructor,
        "student": student,
        "semester_id": semester["id"],
        "department_id": dept["id"],
        "course_id": course["id"],
        "section_id": section["id"],
        "instructor_id": instructor["id"],
        "student_id": student["id"],
    }


def setup_two_departments():
    """Create open-enrollment semester with two departments, each with a course, section, instructor.
    Useful for cross-department tests.
    Returns dict with all entities.
    """
    semester = create_semester()
    sid = semester["id"]

    # Department A
    dept_a = create_department(sid, dept_code="CS", dept_name="Computer Science")
    instructor_a = create_instructor(sid, dept_a["id"])
    course_a = create_course(sid, dept_a["id"], course_code="CS-101", title="Intro CS", credit_hours=3)
    section_a = create_section(sid, dept_a["id"], course_a["id"], instructor_a["id"],
                               schedule_days="MWF", schedule_start="09:00", schedule_end="10:00",
                               location="Room-A")

    # Department B
    dept_b = create_department(sid, dept_code="MATH", dept_name="Mathematics")
    instructor_b = create_instructor(sid, dept_b["id"])
    course_b = create_course(sid, dept_b["id"], course_code="MATH-101", title="Intro Math", credit_hours=3)
    section_b = create_section(sid, dept_b["id"], course_b["id"], instructor_b["id"],
                               schedule_days="TR", schedule_start="11:00", schedule_end="12:00",
                               location="Room-B")

    # Open enrollment
    resp = api_client.open_enrollment(sid, _REG)
    semester = get_success_data(resp)

    return {
        "semester": semester,
        "semester_id": sid,
        "dept_a": dept_a, "dept_a_id": dept_a["id"],
        "dept_b": dept_b, "dept_b_id": dept_b["id"],
        "course_a": course_a, "course_a_id": course_a["id"],
        "course_b": course_b, "course_b_id": course_b["id"],
        "section_a": section_a, "section_a_id": section_a["id"],
        "section_b": section_b, "section_b_id": section_b["id"],
        "instructor_a": instructor_a, "instructor_a_id": instructor_a["id"],
        "instructor_b": instructor_b, "instructor_b_id": instructor_b["id"],
    }


# =============================================================================
# Tier 3: Full Lifecycle — Enrollment lifecycle shortcuts
# =============================================================================

def enroll_student(semester_id, department_id, course_id, section_id, student_id, headers=None):
    """Create an enrollment. Returns enrollment dict."""
    payload = create_enrollment_payload(student_id)
    h = headers or _STU
    resp = api_client.create_enrollment(semester_id, department_id, course_id, section_id, payload, h)
    return get_success_data(resp)


def enroll_and_approve(semester_id, department_id, course_id, section_id, student_id,
                       student_headers=None, prof_headers=None):
    """Enroll a student in a requires_approval section and approve.
    Returns the approved enrollment dict.
    """
    enrollment = enroll_student(semester_id, department_id, course_id, section_id, student_id,
                                headers=student_headers or _STU)
    h = prof_headers or _PROF
    resp = api_client.approve_enrollment(
        semester_id, department_id, course_id, section_id, enrollment["id"], h
    )
    return get_success_data(resp)


def drop_enrollment(semester_id, department_id, course_id, section_id, enrollment_id, headers=None):
    """Drop an enrollment. Returns the dropped enrollment dict."""
    h = headers or _STU
    resp = api_client.drop_enrollment(semester_id, department_id, course_id, section_id, enrollment_id, h)
    return get_success_data(resp)


# =============================================================================
# Tier 4: Accumulation / Threshold Targeting
# =============================================================================

def fill_section_seats(semester_id, department_id, course_id, section_id, count, credit_hours=3):
    """Enroll `count` distinct students into a section to fill seats.
    Returns list of (student, enrollment) tuples.
    """
    dept_id = department_id
    results = []
    for i in range(count):
        student = create_student(semester_id, dept_id, cumulative_gpa=4.0, max_credits=30)
        enrollment = enroll_student(
            semester_id, department_id, course_id, section_id, student["id"]
        )
        results.append((student, enrollment))
    return results


def fill_section_and_waitlist(semester_id, department_id, course_id, section_id,
                               capacity, waitlist_count=0):
    """Fill a section to capacity and optionally place students on waitlist.
    Returns (enrolled_list, waitlisted_list) where each item is (student, enrollment).
    """
    enrolled = fill_section_seats(semester_id, department_id, course_id, section_id, capacity)
    waitlisted = []
    for i in range(waitlist_count):
        student = create_student(semester_id, department_id, cumulative_gpa=4.0, max_credits=30)
        enrollment = enroll_student(
            semester_id, department_id, course_id, section_id, student["id"]
        )
        waitlisted.append((student, enrollment))
    return enrolled, waitlisted


def setup_student_near_credit_limit(semester_id, department_id, instructor_id, student_id,
                                     credits_to_use, credit_hours_per_course=3):
    """Enroll a student in enough courses to use `credits_to_use` credit hours.
    Creates new courses and sections as needed.
    Returns list of (course, section, enrollment) tuples.
    """
    results = []
    remaining = credits_to_use
    idx = 0
    while remaining > 0:
        ch = min(credit_hours_per_course, remaining)
        course = create_course(semester_id, department_id, credit_hours=ch,
                               schedule_days="MWF" if idx % 2 == 0 else "TR",
                               course_code=f"FILL-{idx}")
        # Stagger times to avoid schedule conflicts
        start_hour = 8 + idx
        section = create_section(
            semester_id, department_id, course["id"], instructor_id,
            schedule_days="MWF" if idx % 2 == 0 else "TR",
            schedule_start=f"{start_hour:02d}:00",
            schedule_end=f"{start_hour + 1:02d}:00",
            location=f"Fill-Room-{idx}",
        )
        enrollment = enroll_student(semester_id, department_id, course["id"], section["id"], student_id)
        results.append((course, section, enrollment))
        remaining -= ch
        idx += 1
    return results


# =============================================================================
# Tier 5: Prerequisite Chain Setup
# =============================================================================

def setup_prerequisite_chain(semester_id, department_id, chain_length=3):
    """Create a chain of courses with sequential prerequisites.
    Returns list of courses [root, ..., leaf] where each depends on the previous.
    """
    courses = []
    for i in range(chain_length):
        prereqs = [courses[-1]["id"]] if courses else []
        course = create_course(
            semester_id, department_id,
            course_code=f"CHAIN-{i}",
            title=f"Chain Course {i}",
            credit_hours=3,
            prerequisite_ids=prereqs,
        )
        courses.append(course)
    return courses


# =============================================================================
# Tier 6: Concurrency / Race Condition Setup
# =============================================================================

def setup_race_enrollment_scenario():
    """Setup for concurrent enrollment race tests.
    Creates an open-enrollment semester with a section that has exactly 1 seat.
    Returns dict with semester, department, course, section, instructor, and two students.
    """
    semester = create_semester()
    sid = semester["id"]
    dept = create_department(sid)
    instructor = create_instructor(sid, dept["id"])
    course = create_course(sid, dept["id"], credit_hours=3)
    # Only 1 seat available, no waitlist — second enrollment must fail
    section = create_section(sid, dept["id"], course["id"], instructor["id"], capacity=1, waitlist_cap=0)

    resp = api_client.open_enrollment(sid, _REG)
    semester = get_success_data(resp)

    student_a = create_student(sid, dept["id"])
    student_b = create_student(sid, dept["id"])

    return {
        "semester": semester,
        "semester_id": sid,
        "department": dept,
        "department_id": dept["id"],
        "course": course,
        "course_id": course["id"],
        "section": section,
        "section_id": section["id"],
        "instructor": instructor,
        "instructor_id": instructor["id"],
        "student_a": student_a,
        "student_a_id": student_a["id"],
        "student_b": student_b,
        "student_b_id": student_b["id"],
    }


def setup_waitlist_promotion_scenario(capacity=1, waitlist_count=2):
    """Setup a section with filled capacity and waitlisted students.
    Returns dict with all entities plus the enrolled and waitlisted student info.
    """
    semester = create_semester()
    sid = semester["id"]
    dept = create_department(sid)
    instructor = create_instructor(sid, dept["id"])
    course = create_course(sid, dept["id"], credit_hours=3)
    section = create_section(
        sid, dept["id"], course["id"], instructor["id"],
        capacity=capacity, waitlist_cap=waitlist_count + 5,
    )

    resp = api_client.open_enrollment(sid, _REG)
    semester = get_success_data(resp)

    # Fill all seats
    enrolled_students = []
    for _ in range(capacity):
        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enrollment = enroll_student(sid, dept["id"], course["id"], section["id"], student["id"])
        enrolled_students.append({"student": student, "enrollment": enrollment})

    # Waitlist students
    waitlisted_students = []
    for _ in range(waitlist_count):
        student = create_student(sid, dept["id"], cumulative_gpa=4.0, max_credits=30)
        enrollment = enroll_student(sid, dept["id"], course["id"], section["id"], student["id"])
        waitlisted_students.append({"student": student, "enrollment": enrollment})

    return {
        "semester": semester,
        "semester_id": sid,
        "department": dept,
        "department_id": dept["id"],
        "course": course,
        "course_id": course["id"],
        "section": section,
        "section_id": section["id"],
        "instructor": instructor,
        "instructor_id": instructor["id"],
        "enrolled": enrolled_students,
        "waitlisted": waitlisted_students,
    }


def setup_approval_required_scenario():
    """Setup with a section that requires professor approval.
    Returns dict with all entities.
    """
    semester = create_semester()
    sid = semester["id"]
    dept = create_department(sid)
    instructor = create_instructor(sid, dept["id"])
    course = create_course(sid, dept["id"], credit_hours=3)
    section = create_section(
        sid, dept["id"], course["id"], instructor["id"],
        requires_approval=True, capacity=30,
    )

    resp = api_client.open_enrollment(sid, _REG)
    semester = get_success_data(resp)

    student = create_student(sid, dept["id"])

    return {
        "semester": semester,
        "semester_id": sid,
        "department": dept,
        "department_id": dept["id"],
        "course": course,
        "course_id": course["id"],
        "section": section,
        "section_id": section["id"],
        "instructor": instructor,
        "instructor_id": instructor["id"],
        "student": student,
        "student_id": student["id"],
    }
