"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape (id/timestamps/required fields/
status domain) of a returned resource. Per the PRD, TipAdjustment is the sole
log-style entity and carries no version/updated_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_FULFILLMENT_STATES = {"SCHEDULED", "PLACED", "ROUTED", "PICKED_UP", "DELIVERED", "CANCELLED"}
_BILLING_STATES = {"UNSETTLED", "SETTLED", "REFUNDED"}
_DELIVERY_STATES = {"OFFERED", "ACCEPTED", "EN_ROUTE", "DELIVERED", "REASSIGNED", "CANCELLED"}
_ISSUE_STATES = {"OPEN", "APPROVED", "REJECTED"}
_EARNINGS_STATES = {"ACCRUED", "SETTLED", "REVERSED"}
_LINE_STATES = {"ORDERED", "SHORTED"}


def _assert_common(data: dict):
    """id / created_at / updated_at / version for full common-field entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    for k in (
        "base_delivery_fee_cents", "per_km_fee_cents", "small_order_threshold_cents",
        "small_order_fee_cents", "service_fee_bps", "delivery_fee_cap_cents",
        "dasher_min_guarantee_cents", "dasher_per_km_pay_cents", "dasher_base_pay_cents",
        "active_order_count",
    ):
        assert isinstance(data[k], int), f"{k} must be an integer"
    assert data["active_order_count"] >= 0, "active_order_count must be non-negative"


def assert_restaurant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["zone_id"]), "zone_id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["route_distance_km"], int) and data["route_distance_km"] >= 1
    assert isinstance(data["is_open"], bool)
    assert isinstance(data["prep_minutes"], int) and data["prep_minutes"] >= 1
    assert isinstance(data["max_concurrent_prep"], int) and data["max_concurrent_prep"] >= 1
    assert data["status"] in {"ACTIVE", "DEACTIVATED"}


def assert_menu_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["restaurant_id"]), "restaurant_id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0
    assert isinstance(data["available"], bool)
    assert data["status"] in {"LISTED", "DELISTED"}


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_dasher(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert is_valid_uuid(data["home_zone_id"]), "home_zone_id must be a valid UUID"
    assert isinstance(data["max_batch_size"], int) and data["max_batch_size"] >= 1
    assert isinstance(data["active_delivery_count"], int) and data["active_delivery_count"] >= 0
    assert isinstance(data["lifetime_earnings_cents"], int) and data["lifetime_earnings_cents"] >= 0
    assert data["availability"] in {"ONLINE", "OFFLINE"}


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"]), "customer_id must be a valid UUID"
    assert is_valid_uuid(data["restaurant_id"]), "restaurant_id must be a valid UUID"
    assert is_valid_uuid(data["zone_id"]), "zone_id must be a valid UUID"
    for k in ("order_subtotal_cents", "service_fee_cents", "delivery_fee_quote_cents",
              "tip_cents", "eta_minutes", "refunded_cents"):
        assert isinstance(data[k], int), f"{k} must be an integer"
    assert data["tip_cents"] >= 0, "tip_cents must be non-negative"
    assert data["refunded_cents"] >= 0, "refunded_cents must be non-negative"
    # delivery_fee_final_cents is null until DELIVERED.
    if data.get("delivery_fee_final_cents") is not None:
        assert isinstance(data["delivery_fee_final_cents"], int)
    assert data["fulfillment_status"] in _FULFILLMENT_STATES, \
        f"unexpected fulfillment_status {data['fulfillment_status']!r}"
    assert data["billing_status"] in _BILLING_STATES, \
        f"unexpected billing_status {data['billing_status']!r}"


def assert_order_line_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"]), "order_id must be a valid UUID"
    assert is_valid_uuid(data["menu_item_id"]), "menu_item_id must be a valid UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["extended_price_cents"], int)
    assert isinstance(data["service_fee_cents"], int)
    assert isinstance(data["fulfilled_quantity"], int) and data["fulfilled_quantity"] >= 0
    assert data["status"] in _LINE_STATES


def assert_delivery(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"]), "order_id must be a valid UUID"
    assert is_valid_uuid(data["dasher_id"]), "dasher_id must be a valid UUID"
    assert isinstance(data["route_distance_km"], int)
    assert isinstance(data["pay_quote_cents"], int)
    assert is_iso8601_timestamp(data.get("offered_at", "")), "offered_at must be ISO 8601"
    # settled_pay_cents is null until DELIVERED.
    if data.get("settled_pay_cents") is not None:
        assert isinstance(data["settled_pay_cents"], int)
    assert data["fulfillment_status"] in _DELIVERY_STATES, \
        f"unexpected delivery state {data['fulfillment_status']!r}"


def assert_tip_adjustment(data: dict):
    """Log-style: only id + created_at, NO version, NO updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["order_id"]), "order_id must be a valid UUID"
    assert isinstance(data["delta_cents"], int)
    assert isinstance(data["resulting_tip_cents"], int) and data["resulting_tip_cents"] >= 0


def assert_order_issue(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"]), "order_id must be a valid UUID"
    assert is_valid_uuid(data["line_item_id"]), "line_item_id must be a valid UUID"
    assert isinstance(data["missing_quantity"], int) and data["missing_quantity"] >= 1
    assert data["refund_destination"] in {"ORIGINAL", "WALLET"}
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 0
    assert data["status"] in _ISSUE_STATES


def assert_earnings_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dasher_id"]), "dasher_id must be a valid UUID"
    assert is_valid_uuid(data["delivery_id"]), "delivery_id must be a valid UUID"
    for k in ("base_component_cents", "tip_component_cents", "guarantee_topup_cents"):
        assert isinstance(data[k], int), f"{k} must be an integer"
    if data.get("settled_pay_cents") is not None:
        assert isinstance(data["settled_pay_cents"], int)
    assert data["status"] in _EARNINGS_STATES
