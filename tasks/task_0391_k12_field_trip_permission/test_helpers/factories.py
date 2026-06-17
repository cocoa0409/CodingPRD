"""Payload factories — one per writable entity, input fields only.

Each factory provides PRD-required input fields with sensible defaults and accepts
**overrides so individual tests can pin the values they need to control. Counters
keep emails / labels unique across a single test's setup chain (the server starts
empty before each test, so module-level counters reset per process anyway).
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


# ─── Reference data ───────────────────────────────────────────────────────────
def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Student",
        "grade_level": 5,
        "home_school_code": "SCH1",
    }
    defaults.update(overrides)
    return defaults


def create_guardian_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Guardian",
        "email": unique_email("guardian"),
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "label": "Test Bus",
        "seat_capacity": 40,
    }
    defaults.update(overrides)
    return defaults


def create_scholarship_pool_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Pool",
        "total_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


# ─── FieldTrip ────────────────────────────────────────────────────────────────
def create_field_trip_payload(organizer_teacher_id: str, **overrides) -> dict:
    defaults = {
        "title": "Test Trip",
        "organizer_teacher_id": organizer_teacher_id,
        "school_code": "SCH1",
        "grade_band": "MIDDLE",
        "depart_at": "2026-09-01T09:00:00Z",
        "return_at": "2026-09-01T12:00:00Z",
        "capacity": 10,
        "base_fee_cents": 0,
        "transport_cost_cents": 0,
    }
    defaults.update(overrides)
    return defaults


# ─── PermissionSlip ───────────────────────────────────────────────────────────
def create_permission_slip_payload(student_id: str, guardian_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "guardian_id": guardian_id,
    }
    defaults.update(overrides)
    return defaults


# ─── EmergencyContact ─────────────────────────────────────────────────────────
def create_emergency_contact_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Contact",
        "phone": "555-9999",
        "relationship": "aunt",
    }
    defaults.update(overrides)
    return defaults


# ─── ScholarshipGrant ─────────────────────────────────────────────────────────
def create_scholarship_grant_payload(pool_id: str, award_cents: int, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "award_cents": award_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── Chaperone ────────────────────────────────────────────────────────────────
def create_chaperone_payload(guardian_id: str, **overrides) -> dict:
    defaults = {
        "guardian_id": guardian_id,
    }
    defaults.update(overrides)
    return defaults


# ─── TransportBooking ─────────────────────────────────────────────────────────
def create_transport_booking_payload(vehicle_id: str, seat_count: int, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "seat_count": seat_count,
    }
    defaults.update(overrides)
    return defaults


# ─── Approval ─────────────────────────────────────────────────────────────────
def create_approval_payload(step: str, decision: str, **overrides) -> dict:
    defaults = {
        "step": step,
        "decision": decision,
    }
    defaults.update(overrides)
    return defaults


# ─── Attendance ───────────────────────────────────────────────────────────────
def create_attendance_payload(slip_id: str, checkpoint: str, present: bool, **overrides) -> dict:
    defaults = {
        "slip_id": slip_id,
        "checkpoint": checkpoint,
        "present": present,
    }
    defaults.update(overrides)
    return defaults
