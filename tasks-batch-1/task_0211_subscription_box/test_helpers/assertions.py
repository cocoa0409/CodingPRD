"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates the response structure against the PRD
contract (UUID id, ISO 8601 timestamps, enum membership, field types).
Append-only WalletEntry carries ONLY id + created_at — no updated_at, no version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_audit(data: dict):
    """id + created_at + updated_at + version for every primary resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_plan(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["cadence"] in ("MONTHLY", "QUARTERLY")
    assert isinstance(data["period_price_cents"], int) and data["period_price_cents"] >= 0
    assert isinstance(data["box_item_count"], int) and data["box_item_count"] >= 1
    assert isinstance(data["prepaid_terms_offered"], list)
    assert isinstance(data["prepaid_discount_pct"], (int, float))
    assert 0 <= data["prepaid_discount_pct"] < 1
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_product(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["allocated_qty"], int) and data["allocated_qty"] >= 0
    assert data["status"] in ("SELLABLE", "DISCONTINUED")
    assert_product_invariants(data)


def assert_product_invariants(data: dict):
    """Two-pool stock invariant: available = on_hand - allocated must be >= 0."""
    available = data["on_hand_qty"] - data["allocated_qty"]
    assert available >= 0, (
        f"available (on_hand_qty {data['on_hand_qty']} - allocated_qty "
        f"{data['allocated_qty']}) must never go below zero"
    )


def assert_subscriber(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["wallet_balance_cents"], int)
    assert data["wallet_balance_cents"] >= 0, "wallet_balance_cents may never be negative"


def assert_subscription(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("subscriber_id", "")), "subscriber_id must be a UUID"
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert data["lifecycle_status"] in (
        "ACTIVE", "PAUSED", "CANCEL_SCHEDULED", "CANCELLED", "EXPIRED")
    assert data["billing_status"] in ("CURRENT", "PAST_DUE", "PREPAID")
    assert isinstance(data["is_gift"], bool)
    assert isinstance(data["prepaid_periods_remaining"], int)
    assert isinstance(data["prepaid_unit_value_cents"], int)
    assert isinstance(data["current_period_index"], int)


def assert_gift_grant(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert is_valid_uuid(data.get("gifter_subscriber_id", "")), "gifter_subscriber_id must be a UUID"
    assert isinstance(data["term_periods"], int) and data["term_periods"] >= 1
    assert isinstance(data["recipient_email"], str)
    assert isinstance(data["redemption_code"], str) and len(data["redemption_code"]) > 0
    assert isinstance(data["amount_paid_cents"], int)
    assert data["status"] in ("ISSUED", "REDEEMED", "REVOKED")


def assert_billing_cycle(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("subscription_id", "")), "subscription_id must be a UUID"
    assert isinstance(data["period_index"], int)
    assert isinstance(data["amount_charged_cents"], int)
    assert data["funding_source"] in ("CHARGE", "PREPAID_DRAW", "GIFT", "WALLET")
    assert data["status"] in ("PENDING", "PAID", "FAILED", "REVERSED")


def assert_box_selection(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("subscription_id", "")), "subscription_id must be a UUID"
    assert isinstance(data["period_index"], int)
    assert isinstance(data["product_ids"], list)
    assert data["decision"] in ("PENDING", "CURATED", "SKIPPED", "FINALIZED")


def assert_wave(data: dict):
    _assert_common_audit(data)
    assert data["cadence"] in ("MONTHLY", "QUARTERLY")
    assert is_iso8601_timestamp(data.get("cutoff_at", "")), "cutoff_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ship_date", "")), "ship_date must be ISO 8601"
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert data["reserved_count"] <= data["capacity"], "reserved_count must be <= capacity"
    assert data["status"] in ("OPEN", "LOCKED", "SHIPPED", "CANCELLED")


def assert_allocation(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("subscription_id", "")), "subscription_id must be a UUID"
    assert is_valid_uuid(data.get("wave_id", "")), "wave_id must be a UUID"
    assert is_valid_uuid(data.get("box_selection_id", "")), "box_selection_id must be a UUID"
    assert isinstance(data["line_items"], list)
    assert data["status"] in ("RESERVED", "RELEASED", "COMMITTED")


def assert_shipment(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("allocation_id", "")), "allocation_id must be a UUID"
    assert is_valid_uuid(data.get("wave_id", "")), "wave_id must be a UUID"
    assert is_valid_uuid(data.get("subscription_id", "")), "subscription_id must be a UUID"
    assert data["status"] in ("PACKED", "DISPATCHED", "DELIVERED")


def assert_invoice(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("subscriber_id", "")), "subscriber_id must be a UUID"
    assert isinstance(data["gross_amount_cents"], int)
    assert data["kind"] in ("PERIOD_CHARGE", "PREPAID_CHARGE", "GIFT_CHARGE", "CANCEL_REFUND")
    assert data["status"] in ("SETTLED", "VOID")


def assert_wallet_entry(data: dict):
    """Append-only ledger line: ONLY id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["amount_cents"], int)
    assert data["kind"] in ("REFUND_CREDIT", "WINBACK_CREDIT", "PERIOD_DEBIT", "ADJUSTMENT")
