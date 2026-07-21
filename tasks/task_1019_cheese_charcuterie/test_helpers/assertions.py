"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert data["account_type"] in ("RETAIL", "WHOLESALE_RESTAURANT")
    assert data["wholesale_tier"] in ("NONE", "BRONZE", "SILVER", "GOLD")
    assert data["status"] in ("ACTIVE", "DELINQUENT", "CLOSED")
    assert data["store_credit_cents"] >= 0, "store_credit_cents never negative"


def assert_product(data: dict):
    _assert_common(data)
    assert data["category"] in ("CHEESE", "CHARCUTERIE")
    assert data["pricing_mode"] in ("BY_WEIGHT", "BY_UNIT")
    assert isinstance(data["allergens"], list)


def assert_cave(data: dict):
    _assert_common(data)
    assert data["used_g"] >= 0
    assert data["available_g"] >= 0, "available_g never negative"
    assert data["used_g"] + data["available_g"] == data["capacity_g"], \
        "used_g + available_g must equal capacity_g"


def assert_lot(data: dict):
    _assert_common(data)
    assert data["status"] in ("AGING", "READY", "DEPLETED", "DISCARDED")
    assert data["available_weight_g"] >= 0, "available_weight_g never negative"


def assert_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in ("DRAFT", "SUBMITTED", "FULFILLED", "CANCELLED", "RETURNED")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")


def assert_order_line(data: dict):
    _assert_common(data)
    assert data["line_type"] in ("PRODUCT", "BOARD")


def assert_board(data: dict):
    _assert_common(data)
    assert data["assembly_fee_cents"] >= 0
    assert data["base_price_cents"] >= 0


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_tasting_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_lot_weight_ledger(lot: dict):
    """PRD §2.8 weight ledger: received == current + consumed + cumulative_shrink."""
    assert lot["received_weight_g"] == (
        lot["current_weight_g"] + lot["consumed_weight_g"] + lot["cumulative_shrink_g"]
    ), "received_weight_g must equal current + consumed + cumulative_shrink"
