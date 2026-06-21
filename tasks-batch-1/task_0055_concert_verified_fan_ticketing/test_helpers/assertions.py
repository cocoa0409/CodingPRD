"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_fan(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["device_fingerprint"], str)
    assert isinstance(data["risk_score"], int)
    assert 0 <= data["risk_score"] <= 100
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED", "FLAGGED")
    assert isinstance(data["completed_purchase_count"], int)
    assert data["completed_purchase_count"] >= 0


def assert_event(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str)
    assert data["venue_capacity"] > 0
    assert isinstance(data["presale_code"], str)
    assert data["face_value_cents"] > 0
    assert data["resale_cap_pct"] >= 100
    assert data["tickets_sold_count"] >= 0
    assert data["sales_status"] in ("DRAFT", "PRESALE", "GENERAL", "SOLD_OUT", "CLOSED")


def assert_price_tier(data: dict):
    _assert_common(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["name"], str)
    assert data["allocation"] > 0
    assert data["base_multiplier_bps"] >= 10000
    assert data["reserved_count"] >= 0
    assert data["sold_count"] >= 0
    assert data["reserved_count"] + data["sold_count"] <= data["allocation"]


def assert_queue_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["fan_id"], str)
    assert isinstance(data["tier_id"], str)
    assert isinstance(data["queue_position"], int)
    assert 1 <= data["requested_qty"] <= 6
    assert data["status"] in ("WAITING", "OFFERED", "PURCHASED", "EXPIRED", "REVOKED")


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["queue_entry_id"], str)
    assert isinstance(data["fan_id"], str)
    assert isinstance(data["tier_id"], str)
    assert 1 <= data["quantity"] <= 6
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["service_fee_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["refund_amount_cents"], int)
    assert data["status"] in ("PENDING", "PAID", "REFUNDED", "CANCELLED")


def assert_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["holder_fan_id"], str)
    assert data["entry_status"] in ("VALID", "SCANNED", "VOID")
    assert data["holding_status"] in ("HELD", "TRANSFER_PENDING", "LISTED")


def assert_transfer(data: dict):
    _assert_common(data)
    assert isinstance(data["ticket_id"], str)
    assert isinstance(data["sender_fan_id"], str)
    assert isinstance(data["recipient_fan_id"], str)
    assert data["status"] in ("PENDING", "ACCEPTED", "DECLINED", "CANCELLED")


def assert_resale_listing(data: dict):
    _assert_common(data)
    assert isinstance(data["ticket_id"], str)
    assert isinstance(data["seller_fan_id"], str)
    assert data["list_price_cents"] > 0
    assert data["status"] in ("OPEN", "SOLD", "CANCELLED")
