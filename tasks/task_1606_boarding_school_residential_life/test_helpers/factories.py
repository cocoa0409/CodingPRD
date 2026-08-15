"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "DORM_NAME": "Winslow House",
    "CURFEW_WEEKDAY": "22:30",
    "CURFEW_WEEKEND": "23:30",
    "ROOM_NUMBER": "W-101",
    "BEDS": 2,
    "TERM_NAME": "FALL_2026",
    "TERM_STARTS": "2026-08-24",
    "TERM_ENDS": "2026-12-18",
    "GRADE": 10,
    "GENDER": "MALE",
    "QUESTIONNAIRE": 3,
    "MAX_WARDS": 5,
    "BREAK_NAME": "THANKSGIVING_2026",
    "BREAK_KIND": "THANKSGIVING",
    "BREAK_STARTS": "2026-11-24",
    "BREAK_ENDS": "2026-11-29",
    "UNIT_LABEL": "UNIT-A",
    "UNIT_CAPACITY": 100,
    "DOSES_TOTAL": 10,
    "DUTY_DATE": "2026-09-07",
    "SHIFT_SLOT": "WEEKDAY_NIGHT",
    "LEAVE_DEPARTS": "2026-09-04T17:00:00Z",
    "LEAVE_RETURNS": "2026-09-06T19:00:00Z",
    "HEARING_AT": "2026-09-10T15:00:00Z",
}


def create_term_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["TERM_NAME"],
        "starts_on": DEFAULTS["TERM_STARTS"],
        "ends_on": DEFAULTS["TERM_ENDS"],
    }
    defaults.update(overrides)
    return defaults


def create_dorm_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DORM_NAME"],
        "gender_policy": DEFAULTS.get("GENDER_POLICY", "ANY"),
        "curfew_weekday": DEFAULTS["CURFEW_WEEKDAY"],
        "curfew_weekend": DEFAULTS["CURFEW_WEEKEND"],
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(dorm_id, **overrides) -> dict:
    defaults = {
        "dorm_id": dorm_id,
        "room_number": DEFAULTS["ROOM_NUMBER"],
        "beds": DEFAULTS["BEDS"],
    }
    defaults.update(overrides)
    return defaults


def create_parent_payload(**overrides) -> dict:
    defaults = {"full_name": "Pat Parent", "email": "parent@example.com"}
    defaults.update(overrides)
    return defaults


def create_guardian_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Gua Guardian",
        "email": "guardian@example.com",
        "city": "Boston",
        "max_wards": DEFAULTS["MAX_WARDS"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(staff_role, **overrides) -> dict:
    defaults = {
        "full_name": f"Staff {staff_role}",
        "staff_role": staff_role,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(parent_id, **overrides) -> dict:
    defaults = {
        "legal_name": "Test Student",
        "grade": DEFAULTS["GRADE"],
        "gender": DEFAULTS["GENDER"],
        "is_international": False,
        "parent_id": parent_id,
        "sleep_schedule": DEFAULTS["QUESTIONNAIRE"],
        "cleanliness": DEFAULTS["QUESTIONNAIRE"],
        "noise_tolerance": DEFAULTS["QUESTIONNAIRE"],
        "guests_comfort": DEFAULTS["QUESTIONNAIRE"],
    }
    defaults.update(overrides)
    return defaults


def create_dorm_assignment_payload(student_id, room_id, term_id, expected_student_version,
                                   **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "room_id": room_id,
        "term_id": term_id,
        "expected_student_version": expected_student_version,
    }
    defaults.update(overrides)
    return defaults


def create_leave_request_payload(**overrides) -> dict:
    defaults = {
        "leave_type": "WEEKEND_OVERNIGHT",
        "destination": "Boston",
        "departs_at": DEFAULTS["LEAVE_DEPARTS"],
        "returns_at": DEFAULTS["LEAVE_RETURNS"],
    }
    defaults.update(overrides)
    return defaults


def create_sign_event_payload(student_id, event_type, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "event_type": event_type,
    }
    defaults.update(overrides)
    return defaults


def create_duty_shift_payload(dorm_id, staff_id, expected_dorm_version, **overrides) -> dict:
    defaults = {
        "dorm_id": dorm_id,
        "staff_id": staff_id,
        "duty_date": DEFAULTS["DUTY_DATE"],
        "shift_slot": DEFAULTS["SHIFT_SLOT"],
        "expected_dorm_version": expected_dorm_version,
    }
    defaults.update(overrides)
    return defaults


def create_night_check_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "check_kind": "BED_CHECK",
        "result": "PRESENT",
    }
    defaults.update(overrides)
    return defaults


def create_medication_order_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "medication_name": "Ibuprofen",
        "dose_mg": 200,
        "slot": "MORNING",
        "doses_total": DEFAULTS["DOSES_TOTAL"],
        "is_controlled": False,
        "prescriber_name": "Dr A",
    }
    defaults.update(overrides)
    return defaults


def create_administration_payload(scheduled_date, outcome, **overrides) -> dict:
    defaults = {
        "scheduled_date": scheduled_date,
        "outcome": outcome,
    }
    defaults.update(overrides)
    return defaults


def create_discipline_case_payload(student_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "category": "MINOR",
        "description": "Incident under review",
        "points_proposed": 5,
    }
    defaults.update(overrides)
    return defaults


def create_break_period_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["BREAK_NAME"],
        "kind": DEFAULTS["BREAK_KIND"],
        "starts_on": DEFAULTS["BREAK_STARTS"],
        "ends_on": DEFAULTS["BREAK_ENDS"],
        "housing_available": True,
    }
    defaults.update(overrides)
    return defaults


def create_break_housing_request_payload(break_period_id, **overrides) -> dict:
    defaults = {
        "break_period_id": break_period_id,
        "reason": "Cannot fly home",
    }
    defaults.update(overrides)
    return defaults


def create_storage_unit_payload(**overrides) -> dict:
    defaults = {
        "label": DEFAULTS["UNIT_LABEL"],
        "capacity_cuft": DEFAULTS["UNIT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_storage_reservation_payload(storage_unit_id, break_period_id, **overrides) -> dict:
    defaults = {
        "storage_unit_id": storage_unit_id,
        "break_period_id": break_period_id,
        "volume_cuft": 1,
        "weeks": 1,
        "items_description": "Box",
    }
    defaults.update(overrides)
    return defaults
