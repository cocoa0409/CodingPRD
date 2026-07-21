"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_PRODUCT_STATUSES = {"ACTIVE", "RECALLED", "DISCONTINUED"}
_CATEGORIES = {"HARD_SHELL", "SOFT_SIDE", "BACKPACK", "DUFFEL", "ACCESSORY"}
_TIERS = {"BRONZE", "SILVER", "GOLD", "PLATINUM"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_full_audit(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_product(data: dict):
    _assert_full_audit(data)
    assert data["category"] in _CATEGORIES
    assert data["status"] in _PRODUCT_STATUSES
    for f in ("msrp_cents", "warranty_months", "length_mm", "width_mm", "height_mm"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_customer(data: dict):
    _assert_full_audit(data)
    assert data["tier"] in _TIERS
    assert isinstance(data["lifetime_spend_cents"], int)
    assert isinstance(data["points_balance"], int)
    assert isinstance(data["store_credit_cents"], int)


def assert_registration(data: dict):
    _assert_full_audit(data)
    assert data["status"] in {"ACTIVE", "RECALL_FLAGGED", "VOID"}
    assert is_iso8601_timestamp(data["warranty_expiry"])


def assert_claim(data: dict):
    _assert_full_audit(data)
    assert data["status"] in {
        "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO", "RESOLVED", "REJECTED", "SUPERSEDED",
    }


def assert_repair_order(data: dict):
    _assert_full_audit(data)
    assert data["pay_mode"] in {"CUSTOMER_PAY", "WARRANTY_COVERED"}
    assert isinstance(data["quoted_total_cents"], int)
    assert isinstance(data["warranty_cost_cents"], int)


def assert_sales_order(data: dict):
    _assert_full_audit(data)
    assert data["payment_status"] in {"PENDING", "CAPTURED", "REFUNDED"}
    assert data["fulfillment_status"] in {"UNFULFILLED", "FULFILLED", "CANCELLED"}


def assert_trade_in(data: dict):
    _assert_full_audit(data)
    assert data["status"] in {"OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "VOIDED", "SUPERSEDED"}


def assert_special_order(data: dict):
    _assert_full_audit(data)
    assert data["status"] in {"REQUESTED", "SOURCED", "ARRIVED", "FULFILLED", "CANCELLED"}


def assert_airline_reference_shape(data: dict):
    """Airlines are immutable reference records: id + created_at only (PRD §2.4)."""
    _assert_common(data)
    assert "version" not in data, "Airline must not carry a version field"
    assert "updated_at" not in data, "Airline must not carry an updated_at field"


def assert_customer_ledger_invariants(data: dict):
    """Loyalty-ledger invariants that must always hold (PRD §3.2)."""
    assert data["points_balance"] >= 0, "points_balance must never go negative"
    assert data["store_credit_cents"] >= 0, "store_credit_cents must never go negative"
    assert data["lifetime_spend_cents"] >= 0, "lifetime_spend_cents must never go negative"
