"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_account(data: dict):
    _common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["verification_status"] in ("UNVERIFIED", "VERIFIED")
    assert 0.0 <= data["trust_score"] <= 1.0, "trust_score in [0,1]"
    assert isinstance(data["completed_sales_count"], int)
    assert data["seller_level"] in ("STANDARD", "PRO", "ELITE")
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["strikes"], int)


def assert_sku(data: dict):
    _common(data)
    assert isinstance(data["style_code"], str) and data["style_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["brand"], str) and data["brand"]
    assert isinstance(data["retail_price_cents"], int) and data["retail_price_cents"] > 0
    assert data["release_category"] in ("LIMITED", "GENERAL")


def assert_authenticator(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["location_code"], str) and data["location_code"]
    assert isinstance(data["daily_capacity"], int) and data["daily_capacity"] >= 1


def assert_release(data: dict):
    _common(data)
    assert is_valid_uuid(data["sku_id"])
    assert data["status"] in ("SCHEDULED", "OPEN", "DRAWN", "SETTLED", "CANCELLED")
    assert data["allocated_quantity"] >= 1
    assert data["release_price_cents"] > 0
    for counter in ("entry_count", "winner_count", "reserved_units", "sold_units"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert_release_unit_conservation(data)


def assert_release_unit_conservation(data: dict):
    """PRD §2.9: available_units == allocated_quantity - reserved_units - sold_units."""
    expected = data["allocated_quantity"] - data["reserved_units"] - data["sold_units"]
    assert data["available_units"] == expected, (
        f"unit conservation violated: available_units={data['available_units']} "
        f"but allocated-reserved-sold={expected}"
    )


def assert_raffle_entry(data: dict):
    _common(data)
    assert is_valid_uuid(data["release_id"])
    assert is_valid_uuid(data["account_id"])
    assert data["result"] in ("PENDING", "WON", "LOST")
    assert data["claim_status"] in ("NONE", "CLAIMED", "EXPIRED")
    assert isinstance(data["bot_flag"], bool)


def assert_consignment_item(data: dict):
    _common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["seller_account_id"])
    assert is_valid_uuid(data["sku_id"])
    assert data["declared_condition_grade"] in ("DEADSTOCK", "VNDS", "USED")
    assert data["declared_box_grade"] in ("PERFECT", "GOOD", "DAMAGED", "MISSING")
    assert isinstance(data["declared_accessories_complete"], bool)
    assert data["inspection_result"] in ("PENDING", "PASS", "FAIL")
    assert data["status"] in (
        "INTAKE_PENDING", "RECEIVED", "UNDER_AUTHENTICATION", "AUTHENTICATED", "REJECTED"
    )


def assert_listing(data: dict):
    _common(data)
    assert is_valid_uuid(data["sku_id"])
    assert is_valid_uuid(data["seller_account_id"])
    assert data["condition"] in ("DEADSTOCK", "VNDS", "USED")
    assert data["pricing_mode"] in ("FIXED", "BID_ASK")
    assert data["ask_price_cents"] > 0
    assert data["status"] in ("ACTIVE", "MATCHED")


def assert_bid(data: dict):
    _common(data)
    assert is_valid_uuid(data["sku_id"])
    assert is_valid_uuid(data["buyer_account_id"])
    assert data["amount_cents"] > 0
    assert data["status"] in ("OPEN", "MATCHED")


def assert_order(data: dict):
    _common(data)
    assert is_valid_uuid(data["buyer_account_id"])
    assert data["source_type"] in ("RAFFLE", "FIXED", "BID_MATCH")
    assert data["payment_status"] in ("AUTHORIZED", "CAPTURED", "VOIDED", "REFUNDED")
    assert data["fulfillment_status"] in (
        "AWAITING_SHIPMENT", "IN_AUTHENTICATION", "AUTHENTICATED",
        "FAILED_AUTH", "SHIPPED_TO_BUYER", "VERIFIED",
    )
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] > 0


def assert_dispute(data: dict):
    _common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["filed_by_account_id"])
    assert data["reason"] in ("NOT_AS_DESCRIBED", "NOT_RECEIVED", "INAUTHENTIC")
    assert data["status"] in ("OPEN", "RESOLVED_REFUND", "RESOLVED_DENIED")
