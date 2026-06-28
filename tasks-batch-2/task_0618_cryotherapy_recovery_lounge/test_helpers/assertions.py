"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_location(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["open_booking_count"], int)
    assert data["open_booking_count"] >= 0


def assert_service_type(data: dict):
    _assert_common(data)
    assert data["code"] in ("WHOLE_BODY_CRYO", "RED_LIGHT", "COMPRESSION", "INFRARED_SAUNA")
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 5
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert isinstance(data["credit_cost"], int) and data["credit_cost"] >= 1
    assert isinstance(data["requires_medical_clearance"], bool)
    assert isinstance(data["active"], bool)


def assert_room(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["service_type_id"])
    assert data["status"] == "AVAILABLE"


def assert_technician(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["location_id"])
    assert data["status"] == "ACTIVE"


def assert_shift(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["technician_id"])
    assert is_valid_uuid(data["location_id"])
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_membership_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASE", "PLUS", "ELITE")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["monthly_credit_grant"], int)
    assert isinstance(data["rollover_cap"], int)
    assert isinstance(data["late_cancel_fee_waived"], bool)
    assert isinstance(data["active"], bool)


def assert_member(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["home_location_id"])
    assert isinstance(data["email"], str)
    assert isinstance(data["contraindication_flag"], bool)
    assert isinstance(data["intro_offer_used"], bool)
    assert isinstance(data["credit_balance"], int)
    assert data["credit_balance"] >= 0, "credit_balance is never negative"
    assert data["status"] == "ACTIVE"


def assert_waiver(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["has_contraindication"], bool)
    assert data["status"] in ("ACTIVE", "REVOKED", "SUPERSEDED")


def assert_subscription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in ("ACTIVE", "FROZEN", "CANCELLED")
    assert isinstance(data["granted_credits_remaining"], int)
    assert data["granted_credits_remaining"] >= 0, "granted_credits_remaining never negative"
    assert isinstance(data["freeze_cycles_remaining"], int)
    assert isinstance(data["lifetime_paid_cents"], int)


def assert_credit_pack(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["is_intro"], bool)
    assert isinstance(data["total_credits"], int) and data["total_credits"] >= 1
    assert isinstance(data["remaining_credits"], int)
    assert data["remaining_credits"] >= 0, "remaining_credits never negative"
    assert isinstance(data["price_paid_cents"], int)
    assert data["status"] in ("ACTIVE", "DEPLETED", "REFUNDED", "EXPIRED")


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["location_id"])
    assert is_valid_uuid(data["room_id"])
    assert is_valid_uuid(data["service_type_id"])
    assert isinstance(data["credits_charged"], int)
    assert data["credit_source"] in ("SUBSCRIPTION", "PACK", "SPLIT")
    assert isinstance(data["fee_charged_cents"], int)
    assert data["status"] in ("BOOKED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_invoice(data: dict):
    """Invoice is append-only: id + created_at only, NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Invoice must NOT carry updated_at (append-only)"
    assert "version" not in data, "Invoice must NOT carry version (append-only)"
    assert data["kind"] in ("SIGNUP", "RENEWAL", "UPGRADE_PRORATION", "FREEZE_FEE")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] == "PAID"
