"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_CONDITIONS = ["NEW", "LIKE_NEW", "GOOD", "ACCEPTABLE"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_catalog_item(data: dict):
    _assert_common(data)
    assert isinstance(data["isbn13"], str) and len(data["isbn13"]) == 13
    assert isinstance(data["edition"], int) and data["edition"] >= 1
    for f in ("list_price_cents", "rental_base_cents", "ebook_price_cents",
              "buyback_base_cents", "replacement_fee_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f


def assert_inventory_unit(data: dict):
    _assert_common(data)
    assert data["condition_grade"] in _CONDITIONS
    assert data["status"] in ["AVAILABLE", "RESERVED", "RENTED", "IN_INSPECTION", "RETIRED", "SOLD"]
    assert isinstance(data["times_rented"], int) and data["times_rented"] >= 0


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["wallet_credit_cents"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_type"] in ["RENT", "BUY", "EBOOK"]
    assert data["payment_status"] in ["UNPAID", "PAID", "REFUNDED"]
    assert data["fulfillment_status"] in ["PENDING", "CONFIRMED", "DELIVERED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["quoted_charge_cents"], int)


def assert_rental(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "RETURN_INITIATED", "CLOSED_RETURNED", "CLOSED_LOST"]
    assert isinstance(data["term_days"], int)
    assert isinstance(data["extension_count"], int)


def assert_return_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ["LABEL_ISSUED", "CLOSED_GOOD", "CLOSED_DAMAGED", "CLOSED_LOST"]


def assert_buyback_quote(data: dict):
    _assert_common(data)
    assert data["status"] in ["QUOTED", "ACCEPTED", "REVISED", "PAID", "DECLINED", "SUPERSEDED"]
    assert data["declared_condition"] in _CONDITIONS
    assert isinstance(data["quoted_price_cents"], int)


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "CANCELLED", "SUPERSEDED"]
    assert isinstance(data["monthly_fee_cents"], int)


def assert_wallet_transaction(data: dict):
    """WalletTransaction is append-only: only id + created_at + entry fields.
    It carries NO updated_at and NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["amount_cents"], int)
