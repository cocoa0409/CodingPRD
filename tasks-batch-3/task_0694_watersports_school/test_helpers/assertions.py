"""Entity assertions and domain invariant checkers.

Each assert_<entity>() validates the structural shape of a response object
against the PRD contract using the framework's generic format checkers.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_quartet(data: dict):
    """id + created_at + updated_at + version (entities other than the card)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def assert_school(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["storm_advisory_active"], bool)
    assert data["operating_status"] in ("OPEN", "STORM_CLOSED")
    assert isinstance(data["open_session_count"], int) and data["open_session_count"] >= 0
    # operating_status is fully derived from the advisory flag (PRD §3.1).
    if data["storm_advisory_active"]:
        assert data["operating_status"] == "STORM_CLOSED"
    else:
        assert data["operating_status"] == "OPEN"


def assert_course(data: dict):
    _assert_common_quartet(data)
    assert data["discipline"] in ("SURF", "SAIL", "WINDSURF", "KAYAK")
    assert data["kind"] in ("LESSON", "CERTIFICATION")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["title"], str)


def assert_level(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["rank"], int) and data["rank"] >= 1
    assert isinstance(data["max_students_per_instructor"], int) and \
        data["max_students_per_instructor"] >= 1
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["min_age"], int) and data["min_age"] >= 0
    assert isinstance(data["requires_swim_test"], bool)
    assert data["required_equipment_type"] in ("BOARD", "SAIL_RIG", "KAYAK", "NONE")


def assert_instructor(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["certified_disciplines"], list)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_equipment(data: dict):
    _assert_common_quartet(data)
    assert data["equipment_type"] in ("BOARD", "SAIL_RIG", "KAYAK")
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in ("AVAILABLE", "RENTED", "MAINTENANCE")


def assert_student(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["age_years"], int) and data["age_years"] >= 0
    assert data["swim_test_status"] in ("UNTESTED", "PASSED", "FAILED")
    assert data["waiver_status"] in ("NONE", "SIGNED", "EXPIRED", "REVOKED")


def assert_waiver(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["signed_by"], str)
    assert isinstance(data["is_guardian"], bool)
    assert data["status"] in ("SIGNED", "EXPIRED", "REVOKED")


def assert_membership(data: dict):
    _assert_common_quartet(data)
    assert data["tier"] in ("BASIC", "PREMIUM")
    assert data["status"] in ("ACTIVE", "CANCELLED")
    assert isinstance(data["makeup_credit_balance"], int)


def assert_enrollment(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["planned_sessions"], int) and data["planned_sessions"] >= 1
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["progress_status"] in ("ACTIVE", "COMPLETED", "WITHDRAWN")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert isinstance(data["estimated_price_cents"], int)
    assert isinstance(data["attended_count"], int) and data["attended_count"] >= 0


def assert_session(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["required_instructors"], int) and \
        data["required_instructors"] >= 0
    assert data["status"] in (
        "SCHEDULED", "WEATHER_HOLD", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_booking(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["is_makeup"], bool)
    assert data["status"] in (
        "BOOKED", "CHECKED_IN", "ATTENDED", "NO_SHOW", "CANCELLED")


def assert_rental(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["rental_fee_cents"], int) and data["rental_fee_cents"] >= 0
    assert isinstance(data["deposit_held_cents"], int) and \
        data["deposit_held_cents"] >= 0
    assert data["status"] in ("RESERVED", "ACTIVE", "RETURNED", "CANCELLED")


def assert_certification_card(data: dict):
    """The lean entity: id + created_at only among common fields (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "updated_at" not in data, \
        "CertificationCard must NOT carry updated_at"
    assert "version" not in data, \
        "CertificationCard must NOT carry version"
    assert data["discipline"] in ("SURF", "SAIL", "WINDSURF", "KAYAK")
    assert isinstance(data["card_number"], str) and data["card_number"].startswith("CARD-")
