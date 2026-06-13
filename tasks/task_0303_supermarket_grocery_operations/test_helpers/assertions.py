"""Entity assertions and domain invariant checkers.

Every entity carries id/created_at/updated_at/version (PRD §2.4). Assertions
validate field presence, types, and domain invariants stated in the PRD.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive int, got {data.get('version')!r}"


def assert_department(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["shrink_alert_bps"], int)
    assert 0 <= data["shrink_alert_bps"] <= 10000


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["department_id"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["sell_by_weight"], bool)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["is_perishable"], bool)
    assert isinstance(data["reorder_point_qty"], int) and data["reorder_point_qty"] >= 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["on_hand_value_cents"], int) and data["on_hand_value_cents"] >= 0
    assert isinstance(data["reorder_flagged"], bool)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["received_qty"], int)
    assert isinstance(data["remaining_qty"], int) and data["remaining_qty"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert data["status"] in ("ACTIVE", "QUARANTINED", "DEPLETED", "EXPIRED", "PULLED")


def assert_shipment(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_name"], str)
    assert isinstance(data["reference_code"], str)
    assert isinstance(data["expected_total_cents"], int)
    assert isinstance(data["received_total_cents"], int)
    assert isinstance(data["variance_cents"], int)
    assert data["status"] in ("PENDING", "RECEIVING", "RECEIVED", "REJECTED")


def assert_shipment_line(data: dict):
    _assert_common(data)
    assert isinstance(data["shipment_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["ordered_qty"], int) and data["ordered_qty"] > 0
    assert isinstance(data["accepted_qty"], int) and data["accepted_qty"] >= 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert data["status"] in ("OPEN", "ACCEPTED", "SHORT")


def assert_price_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["ad_price_cents"], int) and data["ad_price_cents"] >= 0
    assert is_iso8601_timestamp(data["effective_start"])
    assert is_iso8601_timestamp(data["effective_end"])
    assert data["status"] in ("SCHEDULED", "ACTIVE", "EXPIRED", "CANCELLED")


def assert_promotion(data: dict):
    _assert_common(data)
    assert isinstance(data["product_id"], str)
    assert data["promo_type"] in ("PERCENT_OFF", "BOGO", "FIXED_OFF")
    assert isinstance(data["min_qty"], int) and data["min_qty"] >= 1
    assert isinstance(data["stackable"], bool)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "EXPIRED", "CANCELLED")


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["points_balance"], int) and data["points_balance"] >= 0
    assert isinstance(data["lifetime_spend_cents"], int) and data["lifetime_spend_cents"] >= 0
    assert data["tier"] in ("BASIC", "SILVER", "GOLD")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_coupon(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["discount_cents"], int) and data["discount_cents"] > 0
    assert isinstance(data["min_spend_cents"], int) and data["min_spend_cents"] >= 0
    assert isinstance(data["stackable"], bool)


def assert_clipped_coupon(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["coupon_id"], str)
    assert data["status"] in ("CLIPPED", "REDEEMED", "EXPIRED")


def assert_sale(data: dict):
    _assert_common(data)
    assert isinstance(data["subtotal_cents"], int) and data["subtotal_cents"] >= 0
    assert isinstance(data["coupon_discount_cents"], int) and data["coupon_discount_cents"] >= 0
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["cogs_cents"], int) and data["cogs_cents"] >= 0
    assert isinstance(data["points_earned"], int) and data["points_earned"] >= 0
    assert data["tender_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("OPEN", "FINALIZED", "VOIDED")


def assert_sale_line_item(data: dict):
    _assert_common(data)
    assert isinstance(data["sale_id"], str)
    assert isinstance(data["product_id"], str)


def assert_cycle_count(data: dict):
    _assert_common(data)
    assert isinstance(data["department_id"], str)
    assert isinstance(data["product_id"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "RECONCILED", "CANCELLED")


def assert_eod(data: dict):
    _assert_common(data)
    assert isinstance(data["department_id"], str)
    assert data["status"] in ("OPEN", "CLOSED")
