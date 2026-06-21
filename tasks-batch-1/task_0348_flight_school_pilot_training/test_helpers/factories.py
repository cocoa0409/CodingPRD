"""Payload factories — one per mutating operation, input fields only.

Each factory returns a dict of the request body for the corresponding POST.
Only fields the PRD marks `source: input` appear; computed/system fields never
do. Optional inputs (is_complex, memo, instructor_id, reported_by_instructor_id,
retry_of_stage_check_id, medical_expiry_date, result_note) are omitted unless
explicitly supplied via overrides.

Email/tail_number uniqueness: every test runs against a fresh database, but
within one test multiple entities may be created, so factories accept a `unique`
discriminator and default to a counter-based one when omitted.
"""
import itertools

_email_counter = itertools.count(1)
_tail_counter = itertools.count(1)


def _next_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_email_counter)}@flightschool.test"


def _next_tail() -> str:
    return f"N{next(_tail_counter):04d}T"


def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Student",
        "email": _next_email("student"),
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Instructor",
        "email": _next_email("instructor"),
        "cfi_rate_cents_per_hour": 6000,
        "authorized_endorsement_codes": ["SOLO", "XC", "COMPLEX", "TAILWHEEL"],
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    defaults = {
        "tail_number": _next_tail(),
        "model": "C172",
        "rental_rate_cents_per_hour": 15000,
        "billing_basis": "HOBBS",
        "initial_hobbs": 100.0,
        "initial_tach": 200.0,
    }
    defaults.update(overrides)
    return defaults


def create_syllabus_payload(**overrides) -> dict:
    defaults = {
        "name": "PRIVATE_PILOT",
        "required_dual_hours": 40,
        "required_solo_hours": 10,
        "stage_count": 3,
        "min_deposit_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id, syllabus_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "syllabus_id": syllabus_id,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(amount_cents, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_squawk_payload(aircraft_id, is_grounding, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "description": "Test maintenance defect",
        "is_grounding": is_grounding,
    }
    defaults.update(overrides)
    return defaults


def create_clearance_payload(clearance_type, decision, **overrides) -> dict:
    defaults = {
        "clearance_type": clearance_type,
        "decision": decision,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(
    enrollment_id, aircraft_id, lesson_type, start_at, end_at,
    estimated_hours, expected_aircraft_version, **overrides,
) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "aircraft_id": aircraft_id,
        "lesson_type": lesson_type,
        "start_at": start_at,
        "end_at": end_at,
        "estimated_hours": estimated_hours,
        "expected_aircraft_version": expected_aircraft_version,
    }
    defaults.update(overrides)
    return defaults


def create_flight_log_payload(
    booking_id, hobbs_start, hobbs_end, tach_start, tach_end, landings, **overrides,
) -> dict:
    defaults = {
        "booking_id": booking_id,
        "hobbs_start": hobbs_start,
        "hobbs_end": hobbs_end,
        "tach_start": tach_start,
        "tach_end": tach_end,
        "landings": landings,
    }
    defaults.update(overrides)
    return defaults


def create_stage_check_payload(enrollment_id, examiner_instructor_id, stage_index, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "examiner_instructor_id": examiner_instructor_id,
        "stage_index": stage_index,
    }
    defaults.update(overrides)
    return defaults


def create_endorsement_payload(enrollment_id, instructor_id, endorsement_code, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "instructor_id": instructor_id,
        "endorsement_code": endorsement_code,
    }
    defaults.update(overrides)
    return defaults
