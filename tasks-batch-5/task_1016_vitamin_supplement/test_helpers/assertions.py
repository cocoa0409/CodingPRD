"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates response shape/typing against the PRD contract.
Domain-invariant checkers enforce the reconciled-ledger identities the PRD
guarantees at the end of every request (§2.6, §3.3).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every persisted resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["form"] in ("CAPSULE", "TABLET", "POWDER", "GUMMY", "LIQUID")
    assert isinstance(data["regimen_goals"], list)
    assert isinstance(data["is_practitioner_line"], bool)
    assert data["dshea_claim_type"] in ("STRUCTURE_FUNCTION", "NONE")
    assert isinstance(data["requires_fda_disclaimer"], bool)
    assert isinstance(data["unit_price_cents"], int)


def assert_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["quantity_received"], int)
    assert isinstance(data["quantity_on_hand"], int)
    assert isinstance(data["quantity_reserved"], int)
    assert isinstance(data["quantity_available"], int)
    assert data["status"] in ("AVAILABLE", "QUARANTINED", "RECALLED", "EXPIRED")
    assert_lot_invariants(data)


def assert_lot_invariants(data: dict):
    """Reconciled-ledger identity (PRD §2.6): available = on_hand - reserved,
    and reserved never negative."""
    assert data["quantity_reserved"] >= 0, "quantity_reserved must not be negative"
    assert data["quantity_available"] == data["quantity_on_hand"] - data["quantity_reserved"], (
        "quantity_available must equal quantity_on_hand - quantity_reserved"
    )


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["lifetime_points_earned"], int)
    assert isinstance(data["points_balance"], int)
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")


def assert_practitioner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["license_number"], str)


def assert_recommendation(data: dict):
    _assert_common(data)
    assert isinstance(data["practitioner_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["max_units"], int)
    assert isinstance(data["consumed_units"], int)
    assert data["status"] in ("ISSUED", "EXHAUSTED", "EXPIRED", "REVOKED")


def assert_bundle(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["component_product_ids"], list)
    assert isinstance(data["discount_pct"], (int, float))


def assert_subscription(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["quantity_per_cycle"], int)
    assert data["cadence_days"] in (30, 60, 90)
    assert isinstance(data["autoship_discount_pct"], (int, float))
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_order(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert data["order_type"] in ("ONE_OFF", "AUTOSHIP")
    assert data["status"] in ("DRAFT", "PLACED", "FULFILLED", "CANCELLED")


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["quantity"], int)
    assert isinstance(data["gross_unit_price_cents"], int)


def assert_return(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["order_line_id"], str)
    assert isinstance(data["quantity"], int)
    assert data["reason"] in ("DEFECT", "UNWANTED", "RECALL", "EXPIRED")
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "REFUNDED")
