"""Payload factories — one per entity, input fields only.

Required vs optional follows the PRD:
- Family.autopay_enabled is optional (defaults false); only email + family_name are required inputs.
- Room.turnover_buffer_minutes optional (default 0); name + capacity required.
- Instructor.max_weekly_sessions optional (default 30); full_name + email required.
- Recital.free_tickets_per_family optional (default 0).
- Costume.rush_surcharge_cents optional (default 0).
- TravelTrip.chaperone_count optional (default 0).
- Enrollment.makeup_for_attendance_id optional.
"""


def create_family_payload(**overrides) -> dict:
    defaults = {"email": "fam@example.com", "family_name": "Test Family"}
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Student", "birth_date": "2014-01-01", "level": "ELITE"}
    defaults.update(overrides)
    return defaults


def create_term_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Term",
        "start_date": "2026-02-01",
        "end_date": "2026-06-30",
        "age_cutoff_date": "2026-02-01",
        "monthly_billing_day": 10,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {"name": "Test Room", "capacity": 20}
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Instructor", "email": "instructor@example.com"}
    defaults.update(overrides)
    return defaults


def create_section_payload(term_id, room_id, instructor_id, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "room_id": room_id,
        "instructor_id": instructor_id,
        "discipline": "JAZZ",
        "required_level": "PETITE",
        "min_age": 5,
        "max_age": 18,
        "monthly_tuition_cents": 8000,
        "capacity_cap": 20,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    defaults = {"day_of_week": 0, "start_minute": 600, "end_minute": 660}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id, section_id, **overrides) -> dict:
    defaults = {"student_id": student_id, "section_id": section_id}
    defaults.update(overrides)
    return defaults


def mark_attendance_payload(session_id, occurred_on, result, **overrides) -> dict:
    defaults = {"session_id": session_id, "occurred_on": occurred_on, "result": result}
    defaults.update(overrides)
    return defaults


def create_costume_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Costume",
        "unit_price_cents": 4500,
        "size_window_close_date": "2026-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_costume_order_payload(costume_id, enrollment_id, **overrides) -> dict:
    defaults = {"costume_id": costume_id, "enrollment_id": enrollment_id, "size_code": "CHILD_M"}
    defaults.update(overrides)
    return defaults


def create_recital_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Recital",
        "show_datetime": "2026-06-20T19:00:00Z",
        "total_seats": 5,
        "ticket_price_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def hold_seat_payload(family_id, seat_label, expected_recital_version, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "seat_label": seat_label,
        "expected_recital_version": expected_recital_version,
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(**overrides) -> dict:
    defaults = {"name": "Test Team", "min_level": "NOVICE", "roster_cap": 10}
    defaults.update(overrides)
    return defaults


def create_membership_payload(student_id, expected_team_version, **overrides) -> dict:
    defaults = {"student_id": student_id, "expected_team_version": expected_team_version}
    defaults.update(overrides)
    return defaults


def create_trip_payload(**overrides) -> dict:
    defaults = {
        "destination": "Test Destination",
        "depart_date": "2026-07-01",
        "return_date": "2026-07-04",
        "per_member_cost_cents": 50000,
        "chaperone_ratio": 4,
        "chaperone_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(membership_id, **overrides) -> dict:
    defaults = {"membership_id": membership_id}
    defaults.update(overrides)
    return defaults


def generate_invoice_payload(family_id, term_id, billing_month, **overrides) -> dict:
    defaults = {"family_id": family_id, "term_id": term_id, "billing_month": billing_month}
    defaults.update(overrides)
    return defaults
