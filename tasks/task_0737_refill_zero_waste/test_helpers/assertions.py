"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates the common structural properties (UUID id,
ISO 8601 created_at) plus the entity's declared fields and enum vocabularies.
Domain invariant checkers validate cross-field rules that must hold after any
operation (non-negative wallet, deposit-float bookkeeping).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_MEMBERSHIP_TIERS = {"BASIC", "PLUS"}
_PRODUCT_CATEGORIES = {"GRAINS", "LIQUIDS", "SPICES", "CLEANING"}
_STATION_STATUSES = {"OPEN", "MAINTENANCE"}
_BIN_STATUSES = {"OPEN", "LOW", "QUARANTINED"}
_CONTAINER_TYPES = {"GLASS_500", "GLASS_1000", "BYO"}
_ALLERGEN_HOLDS = {"NONE", "PEANUT", "GLUTEN", "DAIRY"}
_CONTAINER_STATUSES = {"AVAILABLE", "ISSUED", "IN_USE", "RETURNED", "QUARANTINED", "RETIRED"}
_FULFILLMENT_CHANNELS = {"IN_STORE", "DELIVERY"}
_FULFILLMENT_STATUSES = {"CART", "FILLING", "FILLED", "COMPLETED", "CANCELLED"}
_PAYMENT_STATUSES = {"UNPAID", "CAPTURED"}
_PRICING_STAGES = {"PROVISIONAL", "FINAL", "VOIDED"}
_RESTOCK_STATUSES = {"OPEN", "COMPLETED", "CANCELLED"}
_SUBSCRIPTION_STATUSES = {"ACTIVE", "CANCELLED"}
_DELIVERY_STATUSES = {"SCHEDULED", "DISPATCHED", "DELIVERED", "RETURNED", "CANCELLED"}
_LEDGER_ENTRY_TYPES = {"DEPOSIT_COMMIT", "DEPOSIT_REFUND", "LOYALTY_ACCRUAL", "LOYALTY_REDEEM"}
_LEDGER_SOURCE_KINDS = {"ORDER", "CONTAINER", "DELIVERY"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["membership_tier"] in _MEMBERSHIP_TIERS
    for f in ("wallet_balance_cents", "deposit_liability_cents", "loyalty_points_balance"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["wallet_balance_cents"] >= 0, "wallet balance is non-negative by construction"


def assert_product(data: dict):
    _assert_common(data)
    assert data["category"] in _PRODUCT_CATEGORIES
    assert isinstance(data["unit_price_cents_per_100g"], int)
    assert data["bulk_tier_price_cents_per_100g"] <= data["unit_price_cents_per_100g"]
    assert isinstance(data["allergen_tags"], list)
    assert isinstance(data["taxable"], bool)


def assert_station(data: dict):
    _assert_common(data)
    assert data["station_status"] in _STATION_STATUSES


def assert_bin(data: dict):
    _assert_common(data)
    assert data["status"] in _BIN_STATUSES
    for f in ("capacity_g", "reorder_threshold_g", "on_hand_g", "last_recount_g", "last_shrink_g"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_container(data: dict):
    _assert_common(data)
    assert data["container_type"] in _CONTAINER_TYPES
    assert data["allergen_hold"] in _ALLERGEN_HOLDS
    assert data["status"] in _CONTAINER_STATUSES
    assert isinstance(data["deposit_cents"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_channel"] in _FULFILLMENT_CHANNELS
    assert data["fulfillment_status"] in _FULFILLMENT_STATUSES
    assert data["payment_status"] in _PAYMENT_STATUSES
    for f in ("subtotal_cents", "discount_cents", "deposit_total_cents",
              "tax_cents", "total_cents", "loyalty_points_earned"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_refill_line(data: dict):
    _assert_common(data)
    assert data["pricing_stage"] in _PRICING_STAGES
    assert isinstance(data["net_weight_g"], int)
    assert isinstance(data["line_price_cents"], int)


def assert_restock_task(data: dict):
    _assert_common(data)
    assert data["status"] in _RESTOCK_STATUSES
    assert isinstance(data["requested_fill_g"], int)


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in _SUBSCRIPTION_STATUSES
    assert isinstance(data["version"], int)


def assert_delivery(data: dict):
    _assert_common(data)
    assert data["status"] in _DELIVERY_STATUSES


def assert_wallet_ledger_entry(data: dict):
    """Append-only event: carries id + created_at only, no updated_at/version."""
    _assert_common(data)
    assert data["entry_type"] in _LEDGER_ENTRY_TYPES
    assert data["source_kind"] in _LEDGER_SOURCE_KINDS
    assert "updated_at" not in data, "WalletLedger entries are immutable (no updated_at)"
    assert "version" not in data, "WalletLedger entries are immutable (no version)"


def assert_member_balances(data: dict, *, wallet: int, liability: int, loyalty: int):
    """Assert a member's three ledger projections equal the expected integers."""
    assert data["wallet_balance_cents"] == wallet, \
        f"wallet_balance_cents expected {wallet}, got {data['wallet_balance_cents']}"
    assert data["deposit_liability_cents"] == liability, \
        f"deposit_liability_cents expected {liability}, got {data['deposit_liability_cents']}"
    assert data["loyalty_points_balance"] == loyalty, \
        f"loyalty_points_balance expected {loyalty}, got {data['loyalty_points_balance']}"
