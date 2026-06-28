"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the structural shape of a response object against
the PRD contract. Primary resources carry id/created_at/updated_at/version (§2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_campaign(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["campaign_type"] in ("CATALOG", "PLEDGE", "EVENT")
    assert isinstance(data["goal_cents"], int) and data["goal_cents"] >= 1
    assert isinstance(data["profit_split_pct"], (int, float)) and 0 < data["profit_split_pct"] <= 1
    assert data["posture"] in ("DRAFT", "ACTIVE", "FROZEN", "CLOSED", "RECONCILED", "DISBURSED")
    for f in ("gross_collected_cents", "forecast_gross_cents",
              "school_profit_cents", "vendor_payable_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_prize_tier(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["label"], str)
    assert isinstance(data["threshold_cents"], int) and data["threshold_cents"] >= 1
    assert isinstance(data["prize_description"], str)


def assert_seller(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["guardian_email"], str)
    assert isinstance(data["share_slug"], str) and len(data["share_slug"]) > 0
    assert data["status"] in ("ACTIVE", "BLOCKED")
    assert isinstance(data["credited_cents"], int) and data["credited_cents"] >= 0
    assert data["earned_prize_tier_id"] is None or isinstance(data["earned_prize_tier_id"], str)


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["sku"], str)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 1
    assert isinstance(data["unit_cost_cents"], int) and 0 <= data["unit_cost_cents"] <= data["unit_price_cents"]
    assert isinstance(data["stock_qty"], int) and data["stock_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["seller_id"], str)
    assert data["payment_status"] in ("PENDING", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("PLACED", "CONFIRMED", "DELIVERED", "CANCELLED")
    for f in ("gross_cents", "tax_cents", "total_charged_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"
    assert data["total_charged_cents"] == data["gross_cents"] + data["tax_cents"], \
        "total_charged_cents must equal gross_cents + tax_cents"


def assert_pledge(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["seller_id"], str)
    assert data["status"] in ("PROMISED", "RECORDED", "COLLECTED", "CANCELLED")
    for f in ("per_unit_cents", "flat_cents", "cap_cents", "units_recorded",
              "pledged_amount_cents", "collected_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_volunteer(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["committed_minutes"], int) and data["committed_minutes"] >= 0


def assert_shift(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["role_label"], str)
    assert data["status"] in ("OPEN", "BOOKED", "RELEASED", "CANCELLED")
    assert isinstance(data["setup_buffer_minutes"], int) and data["setup_buffer_minutes"] >= 0


def assert_disbursement(data: dict):
    _assert_common(data)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["school_amount_cents"], int) and data["school_amount_cents"] >= 0
    assert isinstance(data["vendor_amount_cents"], int) and data["vendor_amount_cents"] >= 0
    assert data["status"] == "RECORDED"
