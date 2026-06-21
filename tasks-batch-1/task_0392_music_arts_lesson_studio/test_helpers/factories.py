"""Payload factories — one per entity, input fields only.

Each factory provides PRD-sensible defaults for the input fields of one create
endpoint and accepts **overrides for the values a test needs to control.
"""

DEFAULTS = {
    "STUDIO_NAME": "Test Studio",
    "HOUSEHOLD_NAME": "Test Household",
    "STUDENT_NAME": "Test Student",
    "INSTRUCTOR_NAME": "Test Instructor",
    "ROOM_NAME": "Test Room",
    "HOURLY_RATE_CENTS": 6000,
    "DURATION_MIN": 60,
}


# ---------------- Studio ----------------
def create_studio_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["STUDIO_NAME"]}
    payload.update(overrides)
    return payload


# ---------------- Family ----------------
def create_family_payload(**overrides) -> dict:
    payload = {"household_name": DEFAULTS["HOUSEHOLD_NAME"]}
    payload.update(overrides)
    return payload


# ---------------- Student ----------------
def create_student_payload(family_id: str, **overrides) -> dict:
    payload = {"family_id": family_id, "full_name": DEFAULTS["STUDENT_NAME"]}
    payload.update(overrides)
    return payload


# ---------------- Instructor ----------------
def create_instructor_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["INSTRUCTOR_NAME"],
        "instruments": ["PIANO"],
        "weekly_availability": [{"weekday": 0, "start_min": 0, "end_min": 1440}],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


# ---------------- Room ----------------
def create_room_payload(**overrides) -> dict:
    payload = {
        "room_name": DEFAULTS["ROOM_NAME"],
        "supported_instruments": ["PIANO"],
    }
    payload.update(overrides)
    return payload


# ---------------- Enrollment ----------------
def create_enrollment_payload(
    student_id: str, instructor_id: str, room_id: str, **overrides
) -> dict:
    payload = {
        "student_id": student_id,
        "instructor_id": instructor_id,
        "room_id": room_id,
        "instrument": "PIANO",
        "weekday": 0,
        "start_min": 600,
        "duration_min": DEFAULTS["DURATION_MIN"],
    }
    payload.update(overrides)
    return payload


# ---------------- LessonOccurrence ----------------
def create_occurrence_payload(enrollment_id: str, scheduled_start_utc: str, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "scheduled_start_utc": scheduled_start_utc,
    }
    payload.update(overrides)
    return payload


def create_makeup_occurrence_payload(credit_id: str, scheduled_start_utc: str, **overrides) -> dict:
    payload = {
        "credit_id": credit_id,
        "scheduled_start_utc": scheduled_start_utc,
    }
    payload.update(overrides)
    return payload


# ---------------- TuitionInvoice ----------------
def create_invoice_payload(enrollment_id: str, billing_period: str, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "billing_period": billing_period,
    }
    payload.update(overrides)
    return payload


# ---------------- Payment ----------------
def create_payment_payload(invoice_id: str, **overrides) -> dict:
    payload = {"invoice_id": invoice_id}
    payload.update(overrides)
    return payload


# ---------------- Wallet credit ----------------
def create_wallet_credit_payload(amount_cents: int, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


# ---------------- RecitalEvent ----------------
def create_recital_event_payload(
    venue_capacity: int,
    event_start_utc: str,
    registration_deadline_utc: str,
    **overrides,
) -> dict:
    payload = {
        "title": "Test Recital",
        "venue_capacity": venue_capacity,
        "event_start_utc": event_start_utc,
        "registration_deadline_utc": registration_deadline_utc,
    }
    payload.update(overrides)
    return payload


# ---------------- RecitalRegistration ----------------
def create_registration_payload(recital_event_id: str, student_id: str, **overrides) -> dict:
    payload = {
        "recital_event_id": recital_event_id,
        "student_id": student_id,
    }
    payload.update(overrides)
    return payload


# ---------------- InstrumentRental ----------------
def create_rental_payload(
    family_id: str,
    instrument_unit_code: str,
    period_fee_cents: int,
    rental_start_utc: str,
    rental_end_utc: str,
    **overrides,
) -> dict:
    payload = {
        "family_id": family_id,
        "instrument_unit_code": instrument_unit_code,
        "period_fee_cents": period_fee_cents,
        "rental_start_utc": rental_start_utc,
        "rental_end_utc": rental_end_utc,
    }
    payload.update(overrides)
    return payload


# ---------------- Clock ----------------
def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
