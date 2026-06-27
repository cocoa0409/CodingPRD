"""Entity assertions and domain invariant checkers.

Uses the framework's generic format validators internally. Field names match
the PRD exactly.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["drop_ship_capable"], bool)
    assert isinstance(data["coop_rebate_pct"], (int, float))
    assert 0 <= data["coop_rebate_pct"] <= 0.25
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["sell_mode"] in ("EACH", "BY_FOOT")
    assert isinstance(data["aisle"], str) and len(data["aisle"]) > 0
    assert isinstance(data["bin"], str) and len(data["bin"]) > 0
    assert isinstance(data["on_hand"], (int, float))
    assert data["on_hand"] >= 0, "on_hand floored at 0"
    assert isinstance(data["reorder_needed"], bool)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_contractor_account(data: dict):
    _assert_common(data)
    assert isinstance(data["business_name"], str) and len(data["business_name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 0
    assert data["net_terms_days"] in (0, 15, 30, 45, 60)
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["loyalty_points"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_sales_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in ("DRAFT", "PLACED", "FULFILLED", "CANCELLED")
    assert data["payment_status"] in ("UNBILLED", "INVOICED", "PAID", "VOIDED")
    assert data["pricing_mode"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["loyalty_discount_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] >= 0, "total_cents floored at 0"
    assert isinstance(data["points_accrued"], int)


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["sales_order_id"], str)
    assert isinstance(data["product_id"], str)
    assert data["qty"] > 0
    assert isinstance(data["cut_count"], int) and data["cut_count"] >= 0
    assert isinstance(data["line_total_cents"], int)
    assert data["status"] in ("PENDING", "FULFILLED", "RESTOCKED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["sales_order_id"], str)
    assert isinstance(data["contractor_account_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("ISSUED", "PAID", "VOID")


def assert_rental_asset(data: dict):
    _assert_common(data)
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0
    assert isinstance(data["category"], str) and len(data["category"]) > 0
    assert data["daily_rate_cents"] > 0
    assert data["deposit_cents"] >= 0
    assert data["status"] in ("AVAILABLE", "RENTED", "MAINTENANCE")


def assert_rental_agreement(data: dict):
    _assert_common(data)
    assert isinstance(data["rental_asset_id"], str)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["due_at"])
    assert isinstance(data["rental_charge_cents"], int)
    assert data["status"] in ("RESERVED", "CHECKED_OUT", "RETURNED", "CANCELLED")


def assert_service_station(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert data["status"] in ("ACTIVE", "OFFLINE")


def assert_service_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["service_station_id"], str)
    assert data["service_type"] in ("KEY_CUT", "PAINT_MIX", "PROPANE_EXCHANGE")
    assert isinstance(data["cylinder_certified"], bool)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ("BOOKED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_special_order(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["contractor_account_id"], str)
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert isinstance(data["quoted_unit_cents"], int)
    assert data["qty"] > 0
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["confirmed_total_cents"], int)
    assert data["status"] in ("DRAFT", "QUOTED", "REVISION_REQUESTED",
                              "CONFIRMED", "RECEIVED", "CANCELLED")


def assert_purchase_order(data: dict):
    _assert_common(data)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["lines"], list)
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["coop_rebate_cents"], int)
    assert isinstance(data["net_cost_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "RECEIVED", "CANCELLED")


def assert_loyalty_ledger_entry(data: dict):
    """Immutable audit record — carries ONLY id + created_at (no updated_at,
    no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["delta_points"], int)
    assert data["reason"] in ("ORDER_ACCRUAL", "ORDER_REVERSAL")
    assert isinstance(data["contractor_account_id"], str)


# ─── Domain invariant checkers ──────────────────────────────────────────────

def assert_account_credit_invariants(data: dict):
    """committed_cents includes balance_cents, so committed >= balance; both
    are non-negative integer cents (PRD 2.9)."""
    assert data["balance_cents"] >= 0
    assert data["committed_cents"] >= data["balance_cents"], \
        "committed exposure includes settled balance"


def assert_total_is_subtotal_minus_discount(data: dict):
    """total_cents == max(0, subtotal_cents - loyalty_discount_cents)
    (PRD 3.3)."""
    expected = max(0, data["subtotal_cents"] - data["loyalty_discount_cents"])
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} != "
        f"max(0, {data['subtotal_cents']} - {data['loyalty_discount_cents']})"
    )
