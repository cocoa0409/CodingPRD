"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

# Monotonic counters so factory defaults stay unique within a test run where a
# uniqueness constraint applies (state_student_id, course_code are unique per
# school per §3.2 / §3.4).
_ssid_counter = itertools.count(1)
_course_counter = itertools.count(1)


def create_school_payload(**overrides) -> dict:
    """POST /schools input: name, state_code, ada_method?, minimum_daily_minutes?,
    session_total_days?."""
    defaults = {
        "name": "Test School",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def advance_clock_payload(by_days: int = 1, **overrides) -> dict:
    """POST /schools/{id}/clock/advance input: by_days."""
    defaults = {"by_days": by_days}
    defaults.update(overrides)
    return defaults


def create_student_payload(school_id: str, **overrides) -> dict:
    """POST /students input: school_id, state_student_id, first_name, last_name,
    grade_level, birth_date."""
    defaults = {
        "school_id": school_id,
        "state_student_id": f"SSID-{next(_ssid_counter):05d}",
        "first_name": "Test",
        "last_name": "Student",
        "grade_level": "9",
        "birth_date": "2010-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id: str, entry_day_index: int = 1, **overrides) -> dict:
    """POST /enrollments input: student_id, entry_day_index, fte?."""
    defaults = {
        "student_id": student_id,
        "entry_day_index": entry_day_index,
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(school_id: str, **overrides) -> dict:
    """POST /courses input: school_id, course_code, title, credit_value?, grading_mode?."""
    defaults = {
        "school_id": school_id,
        "course_code": f"C{next(_course_counter):05d}",
        "title": "Test Course",
        "grading_mode": "STANDARDS",
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(course_id: str, period: int = 1, **overrides) -> dict:
    """POST /sections input: course_id, teacher_user_id, period, meeting_minutes?, capacity?."""
    defaults = {
        "course_id": course_id,
        "teacher_user_id": "teacher-1",
        "period": period,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_assignment_payload(enrollment_id: str, section_id: str, **overrides) -> dict:
    """POST /schedule-assignments input: enrollment_id, section_id."""
    defaults = {
        "enrollment_id": enrollment_id,
        "section_id": section_id,
    }
    defaults.update(overrides)
    return defaults


def create_attendance_record_payload(schedule_assignment_id: str, day_index: int, code: str, **overrides) -> dict:
    """POST /attendance-records input: schedule_assignment_id, day_index, code."""
    defaults = {
        "schedule_assignment_id": schedule_assignment_id,
        "day_index": day_index,
        "code": code,
    }
    defaults.update(overrides)
    return defaults


def create_standard_score_payload(schedule_assignment_id: str, standard_code: str, **overrides) -> dict:
    """POST /standard-scores input: schedule_assignment_id, standard_code, mastery_level,
    weight?, percentage_points?."""
    defaults = {
        "schedule_assignment_id": schedule_assignment_id,
        "standard_code": standard_code,
    }
    defaults.update(overrides)
    return defaults


def create_report_card_payload(enrollment_id: str, term_label: str = "Q1", **overrides) -> dict:
    """POST /report-cards input: enrollment_id, term_label."""
    defaults = {
        "enrollment_id": enrollment_id,
        "term_label": term_label,
    }
    defaults.update(overrides)
    return defaults


def create_discipline_incident_payload(enrollment_id: str, category: str = "DISRUPTION",
                                        severity: int = 2, incident_day_index: int = 1,
                                        **overrides) -> dict:
    """POST /discipline-incidents input: enrollment_id, category, severity, incident_day_index."""
    defaults = {
        "enrollment_id": enrollment_id,
        "category": category,
        "severity": severity,
        "incident_day_index": incident_day_index,
    }
    defaults.update(overrides)
    return defaults


def create_consequence_payload(consequence_type: str = "WARNING", **overrides) -> dict:
    """POST /discipline-incidents/{id}/consequences input: type, start_day_index?, duration_days?."""
    defaults = {
        "type": consequence_type,
    }
    defaults.update(overrides)
    return defaults


def create_ada_report_payload(school_id: str, as_of_day_index: int, **overrides) -> dict:
    """POST /ada-funding-reports input: school_id, as_of_day_index."""
    defaults = {
        "school_id": school_id,
        "as_of_day_index": as_of_day_index,
    }
    defaults.update(overrides)
    return defaults


def link_guardian_payload(guardian_user_id: str, **overrides) -> dict:
    """POST /students/{id}/guardians input: guardian_user_id."""
    defaults = {"guardian_user_id": guardian_user_id}
    defaults.update(overrides)
    return defaults
