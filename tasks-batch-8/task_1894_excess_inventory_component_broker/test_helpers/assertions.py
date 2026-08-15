"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_instant_equals(actual: str, expected: str):
    """Compare two ISO 8601 timestamps as instants.

    PRD pins the instant a server-stamped or client-echoed timestamp must
    denote (e.g. §2.4's startup clock), but never pins the string
    representation — with or without fractional digits, both are ISO 8601.
    """
    def _parse(s):
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    assert is_iso8601_timestamp(actual), f"not an ISO 8601 timestamp: {actual!r}"
    assert _parse(actual) == _parse(expected), (
        f"instant mismatch: {actual!r} denotes a different instant than {expected!r}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at one"
    )


def assert_seller(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["payout_terms_days"], int)
    assert isinstance(data["account_balance_cents"], int)
    assert isinstance(data["total_payouts_cents"], int)


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["urgency_tier"] in ("STANDARD", "PRIORITY", "CRITICAL")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["open_order_exposure_cents"], int)


def assert_storage_bin(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bin_code"], str) and data["bin_code"]
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] > 0
    assert isinstance(data["occupied_units"], int)
    assert isinstance(data["available_units"], int)


def assert_buy_offer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("seller_id", ""))
    assert isinstance(data["mpn"], str) and data["mpn"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["ask_price_per_unit_cents"], int)
    assert data["status"] in (
        "PENDING_REVIEW", "ACCEPTED", "REJECTED", "CANCELLED", "UNDER_INSPECTION",
        "INSPECTION_PASSED", "INSPECTION_FAILED", "CONVERTED", "RETURN_PENDING",
        "RETURNED",
    )
    assert data["inspection_result"] in (
        "NONE", "PASS", "FAIL_COUNTERFEIT", "FAIL_DAMAGED", "FAIL_DOCUMENTATION",
    )


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("buy_offer_id", ""))
    assert isinstance(data["mpn"], str) and data["mpn"]
    assert is_valid_uuid(data.get("storage_bin_id", ""))
    assert data["storage_mode"] in ("BROKER_OWNED", "CONSIGNMENT")
    assert isinstance(data["quantity_received"], int)
    for field in ("qty_available", "qty_reserved", "qty_sold", "qty_returned"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["cost_basis_per_unit_cents"], int)
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert isinstance(data["is_counterfeit_suspect"], bool)
    assert data["status"] in (
        "IN_STOCK", "LISTED", "FULLY_RESERVED", "DEPLETED", "QUARANTINED",
    )
    assert isinstance(data["carrying_value_straight_line_cents"], int)
    assert data.get("carrying_value_market_cents") is None or isinstance(
        data["carrying_value_market_cents"], int
    )


def assert_consignment_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("seller_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert is_iso8601_timestamp(data.get("effective_to", ""))
    assert isinstance(data["broker_fee_bps"], int)
    assert data["status"] in ("ACTIVE", "TERMINATED", "EXPIRED")


def assert_market_price_snapshot(data: dict):
    # Append-only record: id + created_at, and explicitly NO updated_at / version.
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "snapshot must not expose updated_at"
    assert "version" not in data, "snapshot must not expose version"
    assert isinstance(data["mpn"], str) and data["mpn"]
    assert isinstance(data["spot_price_cents"], int) and data["spot_price_cents"] > 0
    assert isinstance(data["source"], str) and data["source"]
    assert is_iso8601_timestamp(data.get("observed_at", ""))


def assert_listing(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["asking_price_per_unit_cents"], int)
    assert data.get("recommended_price_per_unit_cents") is None or isinstance(
        data["recommended_price_per_unit_cents"], int
    )
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "WITHDRAWN", "SOLD_OUT")


def assert_sales_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("listing_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["urgency_tier_snapshot"] in ("STANDARD", "PRIORITY", "CRITICAL")
    assert data.get("consignment_fee_bps_snapshot") is None or isinstance(
        data["consignment_fee_bps_snapshot"], int
    )
    assert isinstance(data["provisional_unit_price_cents"], int)
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["required_escrow_cents"], int)
    assert isinstance(data["escrow_funded_cents"], int)
    for nullable in (
        "final_unit_price_cents", "final_total_cents", "customer_refund_cents",
    ):
        assert data.get(nullable) is None or isinstance(data[nullable], int)
    assert data["status"] in (
        "PENDING_ESCROW", "ESCROW_FUNDED", "FULFILLING", "SHIPPED", "DELIVERED",
        "SETTLED", "CANCELLED", "REFUND_PENDING", "REFUNDED",
    )


def assert_escrow_entry(data: dict):
    # Append-only record: id + created_at, and explicitly NO updated_at / version.
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "escrow entry must not expose updated_at"
    assert "version" not in data, "escrow entry must not expose version"
    assert is_valid_uuid(data.get("sales_order_id", ""))
    assert data["entry_type"] in (
        "DEPOSIT", "CUSTOMER_REFUND", "BROKER_FEE", "SELLER_PAYOUT", "BROKER_REVENUE",
    )
    assert isinstance(data["amount_cents"], int)


def assert_return_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("sales_order_id", ""))
    assert data["reason"] in (
        "COUNTERFEIT_SUSPECTED", "DAMAGED", "WRONG_PART", "FAILED_INCOMING_INSPECTION",
    )
    assert data["status"] in (
        "OPENED", "UNDER_REVIEW", "APPROVED", "REJECTED", "REFUND_ISSUED",
    )
    assert data.get("refund_amount_cents") is None or isinstance(
        data["refund_amount_cents"], int
    )


def assert_lot_quantity_invariant(lot: dict):
    """Unit conservation: quantity_received always equals the sum of the four
    quantity buckets."""
    total = (
        lot["qty_available"] + lot["qty_reserved"]
        + lot["qty_sold"] + lot["qty_returned"]
    )
    assert total == lot["quantity_received"], (
        f"lot unit drift: buckets sum to {total}, quantity_received is "
        f"{lot['quantity_received']}"
    )
