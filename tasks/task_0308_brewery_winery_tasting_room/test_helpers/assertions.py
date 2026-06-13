"""Entity assertions and domain invariant checkers.

Structural checks for each primary resource plus reconciliation invariants that
must hold after any operation (product inventory identity, release pool identity).
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_winery(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["ttb_permit_number"], str) and len(data["ttb_permit_number"]) > 0
    assert isinstance(data["home_state_code"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert_winery_invariants(data)


def assert_winery_invariants(data: dict):
    """Premises accounting balances are never negative."""
    assert data["bulk_volume_gallons"] >= 0
    assert data["bottled_taxpaid_volume_gallons"] >= 0
    assert data["excise_tax_owed_cents"] >= 0
    assert data["loyalty_point_liability"] >= 0


def assert_batch(data: dict):
    _assert_common(data)
    assert isinstance(data["winery_id"], str)
    assert isinstance(data["lot_code"], str)
    assert data["beverage_class"] in ("WINE", "BEER", "CIDER")
    assert data["status"] in ("FERMENTING", "AGING", "BOTTLING", "CLOSED", "DUMPED")
    assert_batch_invariants(data)


def assert_batch_invariants(data: dict):
    """available_bulk = volume - loss - bottled, never negative; loss bounded."""
    assert data["available_bulk_gallons"] >= 0
    assert 0 <= data["loss_gallons"] <= data["volume_in_gallons"]
    assert data["bottled_volume_gallons"] >= 0


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["winery_id"], str)
    assert isinstance(data["source_batch_id"], str)
    assert isinstance(data["sku"], str)
    assert isinstance(data["is_age_restricted"], bool)
    assert data["status"] in ("DRAFT", "ACTIVE", "DISCONTINUED")
    assert_product_invariants(data)


def assert_product_invariants(data: dict):
    """free_bottles == on_hand_bottles - allocated_bottles; all non-negative."""
    assert data["on_hand_bottles"] >= 0
    assert data["allocated_bottles"] >= 0
    assert data["free_bottles"] == data["on_hand_bottles"] - data["allocated_bottles"], (
        "free_bottles must equal on_hand_bottles - allocated_bottles"
    )


def assert_release(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")
    assert_release_invariants(data)


def assert_release_invariants(data: dict):
    """available_bottles == pool - reserved - committed, never negative."""
    assert data["reserved_bottles"] >= 0
    assert data["committed_bottles"] >= 0
    assert data["available_bottles"] >= 0
    assert data["available_bottles"] == (
        data["pool_bottles"] - data["reserved_bottles"] - data["committed_bottles"]
    ), "available_bottles must equal pool_bottles - reserved_bottles - committed_bottles"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["status"] in ("PROSPECT", "ACTIVE", "SUSPENDED", "CLOSED")


def assert_membership(data: dict):
    _assert_common(data)
    assert data["tier"] in ("SILVER", "GOLD", "PLATINUM")
    assert data["billing_status"] in ("CURRENT", "PAST_DUE")
    assert data["loyalty_points"] >= 0
    assert data["lifetime_bottles_shipped"] >= 0
    assert data["status"] in ("ENROLLED", "ACTIVE", "PAUSED", "CANCELLED")


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "HELD", "RELEASED", "DELIVERED", "CANCELLED")
    assert data["hold_reason"] in ("NONE", "AGE", "STATE_LIMIT", "BILLING", "WINERY_SUSPENDED")
    assert data["total_cents"] == data["subtotal_cents"] - data["discount_cents"]


def assert_tasting_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "PAID", "VOID", "REFUNDED")
    assert data["total_cents"] >= 0


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "SEATED", "NO_SHOW", "COMPLETED", "CANCELLED"
    )
    assert data["deposit_cents"] >= 0


def assert_distribution_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "SHIPPED", "INVOICED", "CANCELLED")
    assert data["wholesale_total_cents"] >= 0


def assert_ledger_entry(data: dict):
    """Immutable audit event: id + created_at only, NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ledger entry must NOT carry version"
    assert "updated_at" not in data, "ledger entry must NOT carry updated_at"
