"""Payload factories — one per resource, carrying only client-supplied fields."""
import itertools

from .constants import TEST_DEFAULTS

_email_counter = itertools.count(1)
_code_counter = itertools.count(1)


def unique_email(stem: str = "resident") -> str:
    return f"{stem}{next(_email_counter)}@u.edu"


def unique_building_code(stem: str = "KR") -> str:
    return f"{stem}{next(_code_counter):02d}"


def create_building_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["BUILDING_NAME"],
        "code": TEST_DEFAULTS["BUILDING_CODE"],
        "campus_zone": TEST_DEFAULTS["CAMPUS_ZONE"],
    }
    payload.update(overrides)
    return payload


def create_floor_payload(building_id: str, **overrides) -> dict:
    payload = {
        "building_id": building_id,
        "floor_number": TEST_DEFAULTS["FLOOR_NUMBER"],
    }
    payload.update(overrides)
    return payload


def create_room_payload(floor_id: str, **overrides) -> dict:
    payload = {
        "floor_id": floor_id,
        "room_number": TEST_DEFAULTS["ROOM_NUMBER"],
        "bed_capacity": TEST_DEFAULTS["ROOM_BED_CAPACITY"],
        "last_renovation_year": TEST_DEFAULTS["LAST_RENOVATION_YEAR"],
    }
    payload.update(overrides)
    return payload


def create_student_payload(**overrides) -> dict:
    payload = {
        "full_name": "Dee Sun",
        "email": unique_email("dee"),
        "class_year": "JUNIOR",
    }
    payload.update(overrides)
    return payload


def create_application_payload(applicant_student_id: str, **overrides) -> dict:
    payload = {
        "applicant_student_id": applicant_student_id,
        "term_code": TEST_DEFAULTS["TERM_CODE"],
        "essay_ref": "E-ADA",
    }
    payload.update(overrides)
    return payload


def create_duty_shift_payload(floor_id: str, start_at: str, end_at: str, **overrides) -> dict:
    payload = {
        "floor_id": floor_id,
        "shift_type": "WEEKEND",
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload


def create_incident_report_payload(room_id: str, subject_student_id: str, **overrides) -> dict:
    payload = {
        "room_id": room_id,
        "subject_student_id": subject_student_id,
        "occurred_at": "2026-07-30T22:00:00Z",
        "severity": "MODERATE",
        "policy_code": "NOISE",
        "narrative": "Amplified music heard from the corridor after quiet hours.",
    }
    payload.update(overrides)
    return payload


def create_room_inspection_payload(room_id: str, expected_room_version: int, **overrides) -> dict:
    payload = {
        "room_id": room_id,
        "inspection_type": "CHECK_OUT",
        "scheduled_for": "2026-08-05T09:00:00Z",
        "expected_room_version": expected_room_version,
    }
    payload.update(overrides)
    return payload


def complete_room_inspection_payload(**overrides) -> dict:
    payload = {"condition_score": 62, "damage_lines": []}
    payload.update(overrides)
    return payload


def create_room_change_case_payload(
    student_id: str, from_room_id: str, expected_student_version: int, **overrides
) -> dict:
    payload = {
        "student_id": student_id,
        "origin": "SELF_REQUEST",
        "from_room_id": from_room_id,
        "expected_student_version": expected_student_version,
    }
    payload.update(overrides)
    return payload


def create_program_event_payload(floor_id: str, **overrides) -> dict:
    payload = {
        "floor_id": floor_id,
        "title": "Floor Feast",
        "category": "SOCIAL",
        "scheduled_for": "2026-08-03T18:00:00Z",
        "requested_amount_cents": 40_000,
    }
    payload.update(overrides)
    return payload


def create_break_housing_request_payload(student_id: str, room_id: str, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "room_id": room_id,
        "break_code": "WINTER",
        "start_date": "2026-12-18",
        "end_date": "2026-12-24",
        "reason": "research assistantship",
    }
    payload.update(overrides)
    return payload


def damage_line(component_code: str, quantity: int) -> dict:
    return {"component_code": component_code, "quantity": quantity}


def receipt_line(line_category: str, amount_cents: int) -> dict:
    return {"line_category": line_category, "amount_cents": amount_cents}
