"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_member(data: dict):
    _common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["loyalty_points"], int) and data["loyalty_points"] >= 0
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_product(data: dict):
    _common(data)
    assert data["category"] in ("SHOE", "NUTRITION", "GEAR", "APPAREL")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["stock_on_hand"], int) and data["stock_on_hand"] >= 0
    assert isinstance(data["stock_reserved"], int) and data["stock_reserved"] >= 0


def assert_subscription(data: dict):
    _common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "PAST_DUE", "CANCELLED")
    assert data["tier"] in ("CLUB_BASIC", "CLUB_PRO")


def assert_appointment(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")
    assert data["service_type"] in ("GAIT_ANALYSIS", "SHOE_FITTING", "FOLLOWUP")


def assert_session(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "CANCELLED")
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_enrollment(data: dict):
    _common(data)
    assert data["status"] in ("ENROLLED", "WAITLISTED", "CANCELLED")


def assert_event(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert data["active_registrations"] <= data["packet_capacity"], (
        "active_registrations must never exceed packet_capacity"
    )


def assert_registration(data: dict):
    _common(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["packet_status"] in ("RESERVED", "ALLOCATED", "RELEASED")


def assert_order(data: dict):
    _common(data)
    assert data["status"] in ("CART", "PLACED", "FULFILLED", "RETURNED", "CANCELLED")
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0


def assert_shoe_pair(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "REORDER_DUE")


def assert_store(data: dict):
    _common(data)
    assert isinstance(data["session_room_count"], int) and data["session_room_count"] >= 1


def assert_staff(data: dict):
    _common(data)
    assert data["role_type"] in ("FITTER", "COACH", "BOTH")
