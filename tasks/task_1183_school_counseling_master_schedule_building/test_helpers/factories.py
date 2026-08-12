"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


DEFAULTS = {
    "TERM_CODE": "2026-FALL",
    "PERIODS_PER_DAY": 8,
    "MAX_STUDENTS_PER_SECTION": 32,
    "CLASS_SIZE_TARGET": 25,
    "COURSE_CREDITS": 1.0,
    "GRADE_BAND_MIN": 9,
    "GRADE_BAND_MAX": 12,
}


def create_term_payload(**overrides) -> dict:
    defaults = {
        "code": f"{DEFAULTS['TERM_CODE']}-{_seq()}",
        "periods_per_day": DEFAULTS["PERIODS_PER_DAY"],
        "max_students_per_section": DEFAULTS["MAX_STUDENTS_PER_SECTION"],
        "class_size_target": DEFAULTS["CLASS_SIZE_TARGET"],
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(**overrides) -> dict:
    defaults = {
        "course_code": f"C-{_seq()}",
        "title": f"Course {_seq()}",
        "credits": DEFAULTS["COURSE_CREDITS"],
        "subject_area": "ELECTIVE",
        "grade_band_min": DEFAULTS["GRADE_BAND_MIN"],
        "grade_band_max": DEFAULTS["GRADE_BAND_MAX"],
    }
    defaults.update(overrides)
    return defaults


def create_counselor_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Counselor {_seq()}",
        "max_caseload": 100,
    }
    defaults.update(overrides)
    return defaults


def create_teacher_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Teacher {_seq()}",
        "max_sections": 10,
    }
    defaults.update(overrides)
    return defaults


def create_qualification_payload(**overrides) -> dict:
    defaults = {
        "qualified_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "room_number": f"R-{_seq()}",
        "capacity": 32,
        "room_type": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "external_ref": f"S-{n:05d}",
        "full_name": f"Student {n}",
        "grade_level": 9,
        "special_program": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_course_request_payload(**overrides) -> dict:
    defaults = {
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_change_request_payload(**overrides) -> dict:
    defaults = {
        "kind": "ADD",
        "reason": "Schedule adjustment requested",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "start_at": "2026-05-04T09:00:00Z",
        "end_at": "2026-05-04T09:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_recovery_placement_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults
