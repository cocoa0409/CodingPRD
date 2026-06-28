"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def unique_email(prefix: str = "stu") -> str:
    """Generate a unique email so duplicate-email validation does not collide
    across the many students a single test may create."""
    return f"{prefix}-{next(_counter)}@example.com"


# ---- Student (PRD §3.1) ----
def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Student",
        "email": unique_email(),
        # is_international, corporate_contract_id, track are all optional with defaults.
    }
    defaults.update(overrides)
    return defaults


# ---- Corporate Contract (PRD §3.9) ----
def create_corporate_contract_payload(**overrides) -> dict:
    defaults = {
        "company_name": "Test Company",
        "contracted_seats": 5,
        # discount_tier optional, defaults BRONZE.
    }
    defaults.update(overrides)
    return defaults


# ---- Placement Test (PRD §3.1) ----
def create_placement_test_payload(student_id: str, **overrides) -> dict:
    defaults = {"student_id": student_id}
    defaults.update(overrides)
    return defaults


def score_placement_test_payload(raw_score: int, **overrides) -> dict:
    defaults = {"raw_score": raw_score}
    defaults.update(overrides)
    return defaults


# ---- Cohort (PRD §3.2) ----
def create_cohort_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Cohort",
        "level": "B1",
        "track": "GENERAL",
        "capacity": 5,
        "weekly_hours": 18,
        "term_start": "2026-05-04T00:00:00Z",
        "term_end": "2026-08-01T00:00:00Z",
        "total_sessions": 40,
        "base_tuition_cents": 100000,
        "schedule_block": "MORNING",
    }
    defaults.update(overrides)
    return defaults


# ---- Enrollment (PRD §3.3) ----
def create_enrollment_payload(student_id: str, cohort_id: str, **overrides) -> dict:
    defaults = {"student_id": student_id, "cohort_id": cohort_id}
    defaults.update(overrides)
    return defaults


def confirm_enrollment_payload(expected_cohort_version: int, **overrides) -> dict:
    defaults = {"expected_cohort_version": expected_cohort_version}
    defaults.update(overrides)
    return defaults


def terminate_enrollment_payload(termination_reason: str, **overrides) -> dict:
    defaults = {"termination_reason": termination_reason}
    defaults.update(overrides)
    return defaults


# ---- Attendance (PRD §3.5) ----
def create_attendance_payload(enrollment_id: str, session_index: int, status: str = "PRESENT", **overrides) -> dict:
    defaults = {"enrollment_id": enrollment_id, "session_index": session_index, "status": status}
    defaults.update(overrides)
    return defaults


# ---- Progress Report (PRD §3.5) ----
def create_progress_report_payload(enrollment_id: str, speaking=80, listening=80, reading=80, writing=80, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "speaking": speaking,
        "listening": listening,
        "reading": reading,
        "writing": writing,
    }
    defaults.update(overrides)
    return defaults


# ---- Add-on Subscription (PRD §3.6) ----
def create_add_on_payload(student_id: str, enrollment_id: str, add_on_type: str, units: int, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "add_on_type": add_on_type,
        "units": units,
    }
    defaults.update(overrides)
    return defaults


# ---- Close contract (PRD §3.9) ----
def close_contract_payload(expected_contract_version: int, **overrides) -> dict:
    defaults = {"expected_contract_version": expected_contract_version}
    defaults.update(overrides)
    return defaults
