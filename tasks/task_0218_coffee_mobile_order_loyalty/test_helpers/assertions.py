"""Entity assertions and domain invariant checkers for the Coffee Mobile
Order & Loyalty API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id, created_at, updated_at, version for mutable resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_event_common(data: dict):
    """id + created_at only for append-only event logs (PRD §2.4): no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["birth_month_day"], str)
    assert isinstance(data["star_balance"], int) and data["star_balance"] >= 0, \
        "star_balance must be a non-negative int"
    assert isinstance(data["lifetime_stars"], int) and data["lifetime_stars"] >= 0
    assert data["tier"] in ("GREEN", "GOLD")
    assert data["status"] in ("ACTIVE", "CLOSED")


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["timezone"], str)
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 1
    assert isinstance(data["prep_minutes"], int) and data["prep_minutes"] >= 0
    assert data["status"] in ("OPEN", "PAUSED")


def assert_menu_item(data: dict):
    _assert_common(data)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert data["category"] in ("BEVERAGE", "FOOD")
    assert isinstance(data["reward_eligible"], bool)
    assert isinstance(data["available"], bool)


def assert_modifier_option(data: dict):
    _assert_common(data)
    assert isinstance(data["menu_item_id"], str)
    assert data["group_code"] in ("SIZE", "MILK", "SHOT", "SYRUP")
    assert isinstance(data["name"], str)
    assert isinstance(data["price_delta_cents"], int) and data["price_delta_cents"] >= 0
    assert isinstance(data["max_quantity"], int) and data["max_quantity"] >= 1


def assert_stored_value_card(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0, \
        "balance_cents must never be negative"
    assert isinstance(data["auto_reload_enabled"], bool)
    assert isinstance(data["auto_reload_threshold_cents"], int) and data["auto_reload_threshold_cents"] >= 0
    assert isinstance(data["auto_reload_amount_cents"], int) and data["auto_reload_amount_cents"] >= 500


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["store_id"], str)
    assert isinstance(data["pickup_slot_id"], str)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["reward_discount_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["stars_earned"], int)
    assert data["fulfillment_status"] in (
        "CART", "PLACED", "IN_PREP", "READY", "PICKED_UP", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data.get("pay_method") in (None, "STORED_VALUE", "EXTERNAL_CARD")


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["menu_item_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0
    assert isinstance(data["is_reward_redeemed"], bool)


def assert_pickup_slot(data: dict):
    _assert_common(data)
    assert isinstance(data["store_id"], str)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0


def assert_reward_grant(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert data["kind"] in ("FREE_ITEM", "BIRTHDAY")
    assert isinstance(data["star_cost"], int) and data["star_cost"] >= 0
    assert isinstance(data["max_discount_cents"], int) and data["max_discount_cents"] >= 0
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ("ISSUED", "RESERVED", "REDEEMED", "EXPIRED")
    assert data.get("reserved_by_order_id") is None or isinstance(data["reserved_by_order_id"], str)


def assert_refund(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["destination"] in ("STORED_VALUE", "ORIGINAL_METHOD")
    assert isinstance(data["stars_reversed"], int)


def assert_wallet_transaction(data: dict):
    _assert_event_common(data)
    assert "version" not in data, "WalletTransaction is append-only: must not carry a version field"
    assert "updated_at" not in data, "WalletTransaction is append-only: must not carry updated_at"
    assert isinstance(data["card_id"], str)
    assert data["kind"] in ("RELOAD", "AUTO_RELOAD", "ORDER_SPEND", "REFUND")
    assert isinstance(data["amount_cents"], int)


def assert_star_ledger_entry(data: dict):
    _assert_event_common(data)
    assert "version" not in data, "StarLedgerEntry is append-only: must not carry a version field"
    assert "updated_at" not in data, "StarLedgerEntry is append-only: must not carry updated_at"
    assert isinstance(data["member_id"], str)
    assert data["kind"] in ("EARN", "REDEEM", "REVERSAL")
    assert isinstance(data["delta_stars"], int)
