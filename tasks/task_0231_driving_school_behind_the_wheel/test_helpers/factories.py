"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


# ---------------------------------------------------------------------------
# CoursePackage (§3.1)
# ---------------------------------------------------------------------------
def create_course_package_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("PKG"),
        "name": "Test Package",
        "price_cents": 90000,
        "enrollment_fee_cents": 5000,
        "included_classroom_hours": 30,
        "included_online_hours": 8,
        "included_road_hours": 6,
        "bundle_discount_cents": 5000,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Student (§3.2)
# ---------------------------------------------------------------------------
def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Student",
        "email": _uniq("stu") + "@x.com",
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# GuardianConsent (§3.2)
# ---------------------------------------------------------------------------
def create_guardian_consent_payload(student_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "guardian_name": "Test Guardian",
        "guardian_email": _uniq("guard") + "@x.com",
        "relationship": "PARENT",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Enrollment (§3.4)
# ---------------------------------------------------------------------------
def create_enrollment_payload(student_id: str, package_id: str, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "package_id": package_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Instructor (§3.6)
# ---------------------------------------------------------------------------
def create_instructor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Instructor",
        "email": _uniq("inst") + "@x.com",
        "certified_road": True,
        "hourly_rate_cents": 5000,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Vehicle (§3.6)
# ---------------------------------------------------------------------------
def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "plate": _uniq("PLATE"),
        "dual_control": True,
        "prep_buffer_minutes": 0,
        "out_of_service": False,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Lesson (§3.6) — expected_student_version is mandatory (no default).
# ---------------------------------------------------------------------------
def create_lesson_payload(student_id: str, enrollment_id: str, lesson_type: str,
                          start_at: str, end_at: str, expected_student_version: int,
                          **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "lesson_type": lesson_type,
        "start_at": start_at,
        "end_at": end_at,
        "expected_student_version": expected_student_version,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# WalletEntry (§3.10 admin adjustment)
# ---------------------------------------------------------------------------
def create_wallet_entry_payload(student_id: str, amount_cents: int,
                                reason: str = "ADMIN_ADJUSTMENT", **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "amount_cents": amount_cents,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults
