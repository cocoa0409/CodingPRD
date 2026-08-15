"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import (
    STD_ENDS, STD_MEETING_END, STD_MEETING_START, STD_REG_CLOSES, STD_REG_OPENS,
    STD_ROOM, STD_STARTS, STD_TERM,
)

_counter = {"n": 0}


def _seq() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_building_payload(**overrides) -> dict:
    n = _seq()
    defaults = {"name": f"Building {n}", "building_code": f"BLD-{n}"}
    defaults.update(overrides)
    return defaults


def create_budget_payload(building_id, **overrides) -> dict:
    defaults = {"building_id": building_id, "fiscal_year": 2026, "allocated_cents": 500000}
    defaults.update(overrides)
    return defaults


def create_employee_payload(primary_building_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Employee {n}",
        "email": f"emp{n}@example.com",
        "employee_kind": "TEACHER",
        "primary_building_id": primary_building_id,
        "base_lane": "BA",
    }
    defaults.update(overrides)
    return defaults


def create_course_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "course_code": f"CRS-{n}",
        "title": f"Course {n}",
        "delivery_mode": "IN_PERSON",
        "clock_hours": 10,
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(course_id, instructor_id, building_id, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "term": STD_TERM,
        "instructor_id": instructor_id,
        "building_id": building_id,
        "room": STD_ROOM,
        "seat_capacity": 5,
        "starts_at": STD_STARTS,
        "ends_at": STD_ENDS,
        "registration_opens_at": STD_REG_OPENS,
        "registration_closes_at": STD_REG_CLOSES,
    }
    defaults.update(overrides)
    return defaults


def create_meeting_payload(**overrides) -> dict:
    defaults = {
        "starts_at": STD_MEETING_START,
        "ends_at": STD_MEETING_END,
        "room": STD_ROOM,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(teacher_id, section_id, **overrides) -> dict:
    defaults = {"teacher_id": teacher_id, "section_id": section_id}
    defaults.update(overrides)
    return defaults


def create_survey_payload(**overrides) -> dict:
    defaults = {"overall_rating": 4, "would_recommend": True}
    defaults.update(overrides)
    return defaults


def create_workshop_payload(teacher_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "teacher_id": teacher_id,
        "title": f"Workshop {n}",
        "provider": "External Provider",
        "starts_at": "2026-12-01T09:00:00Z",
        "ends_at": "2026-12-02T17:00:00Z",
        "est_cost_cents": 30000,
        "clock_hours_claimed": 8,
    }
    defaults.update(overrides)
    return defaults


def create_growth_plan_payload(teacher_id, expected_employee_version, **overrides) -> dict:
    defaults = {
        "teacher_id": teacher_id,
        "school_year": "2026-2027",
        "focus_areas": ["math"],
        "target_credits": 2.0,
        "expected_employee_version": expected_employee_version,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(employee_id, course_id, **overrides) -> dict:
    defaults = {
        "employee_id": employee_id,
        "course_id": course_id,
        "due_date": "2027-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_audit_case_payload(employee_id, **overrides) -> dict:
    defaults = {"employee_id": employee_id, "fiscal_year": 2026}
    defaults.update(overrides)
    return defaults
