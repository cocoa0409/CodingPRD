"""Entity assertions and domain invariant checkers.

Each assert_* checks the common resource properties the PRD guarantees
(id UUID, ISO 8601 timestamps, integer version) plus the status enum and the
core typed fields the PRD names for that resource's read representation.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_tour(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["artist_name"], str) and data["artist_name"]
    for field in ("standard_rate_bps", "tier_threshold_cents", "tier_bonus_bps",
                  "licensed_flat_per_unit_cents", "licensed_rate_bps",
                  "cash_variance_tolerance_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["default_size_curve"], dict)
    assert data["status"] in ("PLANNING", "ACTIVE", "CLOSED")
    assert "royalty_payable_cents" in data, "tour read must report royalty_payable_cents"
    assert isinstance(data["royalty_payable_cents"], int)


def assert_show(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_id"], str)
    assert isinstance(data["city"], str) and data["city"]
    assert isinstance(data["venue_name"], str) and data["venue_name"]
    assert isinstance(data["show_date"], str) and data["show_date"]
    assert data["commission_mode"] in ("FLAT", "TIERED")
    assert data["status"] in ("SCHEDULED", "OPEN", "RECONCILING", "SETTLED",
                              "CLOSED", "CANCELLED")
    assert "settlement_id" in data, "show read must carry settlement_id"
    assert "closeout_credit_cents" in data, "show read must carry closeout_credit_cents"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_id"], str)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["product_type"] in ("REGULAR", "BUNDLE")
    assert data["royalty_treatment"] in ("STANDARD", "LICENSED")
    assert isinstance(data["sized"], bool)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["initial_stock_by_size"], dict)
    assert "warehouse_stock_by_size" in data, "product read must report warehouse_stock_by_size"
    assert isinstance(data["warehouse_stock_by_size"], dict)
    for size_key, units in data["warehouse_stock_by_size"].items():
        assert isinstance(units, int) and units >= 0, \
            f"warehouse stock for {size_key} must be a non-negative integer"


def assert_show_product(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0


def assert_allocation(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["product_id"], str)
    assert data["size"] in ("S", "M", "L", "XL", "OS")
    for field in ("quantity_allocated", "quantity_sold", "quantity_returned",
                  "quantity_liquidated", "quantity_shrunk", "quantity_on_hand"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"{field} must be a non-negative integer"


def assert_allocation_conservation(data: dict):
    """Post-close-out conservation invariant: allocated == sold + returned +
    liquidated + shrunk."""
    total = (data["quantity_sold"] + data["quantity_returned"]
             + data["quantity_liquidated"] + data["quantity_shrunk"])
    assert data["quantity_allocated"] == total, (
        f"conservation violated: allocated {data['quantity_allocated']} != "
        f"sold {data['quantity_sold']} + returned {data['quantity_returned']} + "
        f"liquidated {data['quantity_liquidated']} + shrunk {data['quantity_shrunk']}")


def assert_seller(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_id"], str)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["seller_code"], str) and data["seller_code"]


def assert_seller_session(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert isinstance(data["seller_id"], str)
    assert isinstance(data["cash_float_cents"], int) and data["cash_float_cents"] >= 0
    assert data["status"] in ("OPEN", "COUNTED_OUT", "VERIFIED", "LOCKED")
    assert isinstance(data["expected_cash_cents"], int)
    assert "counted_cash_cents" in data
    assert "cash_variance_cents" in data
    assert "verified_by_user_id" in data
    assert isinstance(data["recount_count"], int) and data["recount_count"] >= 0


def assert_sale_record(data: dict):
    _assert_common(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["allocation_id"], str)
    assert isinstance(data["show_id"], str), "sale record must denormalize show_id"
    assert isinstance(data["product_id"], str), "sale record must denormalize product_id"
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["tender"] in ("CASH", "CARD")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert data["gross_cents"] == data["quantity"] * data["unit_price_cents"], (
        f"gross_cents {data['gross_cents']} != quantity x unit_price "
        f"{data['quantity']} x {data['unit_price_cents']}")
    assert data["status"] in ("ACTIVE", "VOIDED")
    assert "void_reason" in data
    assert "voided_by_user_id" in data


def assert_online_order(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_id"], str)
    assert isinstance(data["product_id"], str)
    assert "size" in data
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert data["gross_cents"] == data["quantity"] * data["unit_price_cents"]
    assert isinstance(data["artist_royalty_provisional_cents"], int)
    assert isinstance(data["licensing_provisional_cents"], int)
    assert "artist_royalty_final_cents" in data
    assert "licensing_final_cents" in data
    assert data["status"] in ("PLACED", "FULFILLED", "CANCELLED")


def assert_settlement(data: dict):
    _assert_common(data)
    assert isinstance(data["show_id"], str)
    assert data["status"] in ("PROVISIONAL", "RECONCILED", "DISPUTED", "FINALIZED")
    assert isinstance(data["provisional_gross_cents"], int)
    assert isinstance(data["venue_commission_provisional_cents"], int)
    for field in ("pinned_standard_rate_bps", "pinned_tier_threshold_cents",
                  "pinned_tier_bonus_bps", "pinned_licensed_flat_per_unit_cents",
                  "pinned_licensed_rate_bps"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    for field in ("final_gross_cents", "venue_commission_final_cents",
                  "net_to_tour_cents", "artist_royalty_cents", "licensing_cents",
                  "company_share_cents", "reconciled_by_user_id", "dispute_reason"):
        assert field in data, f"settlement read must carry {field}"


def assert_settlement_final_figures(data: dict):
    """Final-variant arithmetic identities that must hold once reconciled."""
    assert (data["net_to_tour_cents"]
            == data["final_gross_cents"] - data["venue_commission_final_cents"]), (
        "net_to_tour_cents must equal final_gross_cents - venue_commission_final_cents")
    assert (data["company_share_cents"]
            == data["net_to_tour_cents"] - data["artist_royalty_cents"]
            - data["licensing_cents"]), (
        "company_share_cents must equal net - artist royalty - licensing")


def assert_shipment(data: dict):
    _assert_common(data)
    assert isinstance(data["tour_id"], str)
    assert data["origin_type"] in ("WAREHOUSE", "SHOW")
    assert "origin_show_id" in data
    assert isinstance(data["destination_show_id"], str)
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["status"] in ("DRAFT", "DISPATCHED", "RECEIVED", "CANCELLED")
    assert "dispatched_by_user_id" in data
    assert "dispatched_at" in data
    assert "received_by_user_id" in data
