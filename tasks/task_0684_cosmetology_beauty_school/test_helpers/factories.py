"""Payload factories — one per entity, input fields only (PRD §3).

Each factory provides PRD-valid defaults and accepts **overrides. Email and
license_number defaults are unique-per-call (uniqueness is enforced by the PRD)
so back-to-back factory calls within one test do not collide.
"""
import itertools

_email_seq = itertools.count(1)
_license_seq = itertools.count(1)


def create_program_payload(**overrides) -> dict:
    """PRD §3.1. Required: name, total_clock_hours, tuition_cents, kit_fee_cents,
    lab_fee_cents, clinic_phase_start_hour. Optional: clock_hours_per_credit
    (default 37.5), admin_fee_cap_cents (default 15000)."""
    defaults = {
        "name": "Cosmetology 1500",
        "total_clock_hours": 1500,
        "tuition_cents": 1200000,
        "kit_fee_cents": 150000,
        "lab_fee_cents": 50000,
        "clinic_phase_start_hour": 300,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    """PRD §3.1. Required: full_name, email, ssn_last4."""
    n = next(_email_seq)
    defaults = {
        "full_name": "Test Student",
        "email": f"student{n}@x.com",
        "ssn_last4": "1234",
    }
    defaults.update(overrides)
    return defaults


def create_instructor_payload(**overrides) -> dict:
    """PRD §3.1. Required: full_name, license_number, license_expires_on.
    Optional: active (default true)."""
    n = next(_license_seq)
    defaults = {
        "full_name": "Test Instructor",
        "license_number": f"INS-{n}",
        "license_expires_on": "2027-01-01T00:00:00Z",
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(**overrides) -> dict:
    """PRD §3.1. Required: label, station_type."""
    defaults = {
        "label": "Styling-1",
        "station_type": "HAIR",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id, program_id, **overrides) -> dict:
    """PRD §3.2. Required: student_id, program_id, enrolled_on_iso.
    Optional: scheduled_hours_to_date (default 0)."""
    defaults = {
        "student_id": student_id,
        "program_id": program_id,
        "enrolled_on_iso": "2026-04-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_attendance_payload(enrollment_id, instructor_id, **overrides) -> dict:
    """PRD §3.3. Required: enrollment_id, instructor_id, session_date_iso,
    scheduled_hours, hours. Optional: record_type (default REGULAR)."""
    defaults = {
        "enrollment_id": enrollment_id,
        "instructor_id": instructor_id,
        "session_date_iso": "2026-05-01T00:00:00Z",
        "scheduled_hours": 50,
        "hours": 50,
    }
    defaults.update(overrides)
    return defaults


def create_clinic_ticket_payload(enrollment_id, station_id, instructor_id, **overrides) -> dict:
    """PRD §3.3. Required: enrollment_id, station_id, instructor_id, client_name,
    start_iso, end_iso, line_items. Optional: clinic_discount_pct (default 0.50)."""
    defaults = {
        "enrollment_id": enrollment_id,
        "station_id": station_id,
        "instructor_id": instructor_id,
        "client_name": "Walk In",
        "start_iso": "2026-06-01T10:00:00Z",
        "end_iso": "2026-06-01T11:00:00Z",
        "line_items": [{"service_code": "CUT", "salon_price_cents": 4000}],
        "clinic_discount_pct": 0.50,
    }
    defaults.update(overrides)
    return defaults


def create_station_assignment_payload(station_id, enrollment_id, instructor_id, **overrides) -> dict:
    """PRD §3.3. Required: station_id, enrollment_id, instructor_id,
    start_iso, end_iso."""
    defaults = {
        "station_id": station_id,
        "enrollment_id": enrollment_id,
        "instructor_id": instructor_id,
        "start_iso": "2026-06-01T10:00:00Z",
        "end_iso": "2026-06-01T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(enrollment_id, **overrides) -> dict:
    """PRD §3.4. Required: enrollment_id, payment_period, period_hours,
    period_weeks, gross_amount_cents. Optional: origination_fee_cents (default 0)."""
    defaults = {
        "enrollment_id": enrollment_id,
        "payment_period": 1,
        "period_hours": 400,
        "period_weeks": 4,
        "gross_amount_cents": 600000,
        "origination_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_exam_application_payload(enrollment_id, **overrides) -> dict:
    """PRD §3.7. Required: enrollment_id, exam_type, mock_exam_avg,
    competency_signoff_pct."""
    defaults = {
        "enrollment_id": enrollment_id,
        "exam_type": "WRITTEN",
        "mock_exam_avg": 85,
        "competency_signoff_pct": 100,
    }
    defaults.update(overrides)
    return defaults


def create_withdrawal_payload(enrollment_id, **overrides) -> dict:
    """PRD §3.6. Required: enrollment_id, withdrawal_type,
    last_date_of_attendance_iso."""
    defaults = {
        "enrollment_id": enrollment_id,
        "withdrawal_type": "OFFICIAL",
        "last_date_of_attendance_iso": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
