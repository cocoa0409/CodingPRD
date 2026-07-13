"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_rink(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["public_skate_capacity"] >= 1
    assert data["resurface_buffer_minutes"] >= 0
    assert data["available_rental_skates"] <= data["rental_skate_count"]
    assert data["available_lockers"] <= data["locker_count"]


def assert_skater(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["membership"] in ("MEMBER", "NON_MEMBER")
    assert isinstance(data["wallet_credit_cents"], int)


def assert_ice_slot(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["purpose"] in (
        "PUBLIC_SKATE", "LEARN_TO_SKATE", "LEAGUE", "RENTAL", "BROOMBALL", "PARTY",
    )


def assert_admission(data: dict):
    _assert_common(data)
    assert data["status"] in ("ADMITTED", "EXITED", "REFUNDED")
    assert isinstance(data["captured_cents"], int)
    assert isinstance(data["refunded_cents"], int)


def assert_class(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "FULL", "CANCELLED", "COMPLETED")
    assert data["capacity"] >= 1


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "COMPLETED", "WITHDRAWN")


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PAST_DUE", "CANCELLED")
    assert isinstance(data["captured_cents"], int)


def assert_league(data: dict):
    _assert_common(data)
    assert data["status"] in ("REGISTRATION_OPEN", "IN_SEASON", "CANCELLED")
    assert data["sport"] in ("HOCKEY", "FIGURE")


def assert_registration(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_locker_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "RELEASED")
    assert data["locker_number"] >= 1


def assert_slot_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "CANCELLED")
    assert data["booking_type"] in ("PRIVATE_RENTAL", "BROOMBALL", "PARTY")


def assert_sharpening_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "IN_PROGRESS", "READY", "PICKED_UP")
