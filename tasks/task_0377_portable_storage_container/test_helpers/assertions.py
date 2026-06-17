"""Entity assertions and domain invariant checkers.

Uses the framework's generic format helpers internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_AGREEMENT_LIFECYCLE = {
    "QUOTED", "RESERVED", "ACTIVE", "ON_HOLD", "CLOSING", "CLOSED", "CANCELLED",
}
_BILLING_STATUS = {"CURRENT", "PAST_DUE", "DELINQUENT"}
_UNIT_STATUS = {"RESERVED", "DELIVERED", "ON_SITE", "IN_TRANSIT", "RETURNED", "RELEASED"}
_SIZE_CODES = {"C8", "C12", "C16"}
_TIER_CODES = {"NONE", "BASIC", "PLUS", "PREMIER"}
_CHARGE_TYPES = {
    "DELIVERY_FEE", "RENTAL_PRORATION", "RENTAL_CYCLE", "PROTECTION_PREMIUM",
    "PACKING_SUPPLIES", "MOVE", "ACCESS_FEE", "LATE_FEE", "PAYMENT", "ADJUSTMENT",
}


def _assert_common_mutable(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def _assert_common_immutable(data: dict):
    """id + created_at only; no updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable entity must not expose a version field"
    assert "updated_at" not in data, "immutable entity must not expose an updated_at field"


def assert_container_model(data: dict):
    _assert_common_immutable(data)
    assert data["size_code"] in _SIZE_CODES
    assert isinstance(data["cubic_feet"], int) and data["cubic_feet"] >= 1
    assert isinstance(data["monthly_rate_cents"], int) and data["monthly_rate_cents"] >= 0
    assert isinstance(data["delivery_fee_cents"], int) and data["delivery_fee_cents"] >= 0
    assert isinstance(data["footprint_sqft"], int) and data["footprint_sqft"] >= 1


def assert_protection_plan(data: dict):
    _assert_common_immutable(data)
    assert data["tier_code"] in _TIER_CODES
    assert isinstance(data["base_premium_cents"], int) and data["base_premium_cents"] >= 0
    assert isinstance(data["rate_bps"], int) and data["rate_bps"] >= 0
    assert isinstance(data["min_premium_cents"], int) and data["min_premium_cents"] >= 0
    assert isinstance(data["coverage_cap_cents"], int) and data["coverage_cap_cents"] >= 0


def assert_depot_inventory(data: dict):
    _assert_common_mutable(data)
    assert data["size_code"] in _SIZE_CODES
    for f in ("total_units", "reserved_units", "committed_units", "available_units"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"
    assert_inventory_invariant(data)


def assert_inventory_invariant(data: dict):
    """PRD §2.6: available_units = total_units - reserved_units - committed_units."""
    assert data["available_units"] == (
        data["total_units"] - data["reserved_units"] - data["committed_units"]
    ), "available_units must equal total_units - reserved_units - committed_units"


def assert_customer(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["lifetime_paid_cents"], int) and data["lifetime_paid_cents"] >= 0
    assert isinstance(data["open_balance_cents"], int)


def assert_rental_agreement(data: dict):
    _assert_common_mutable(data)
    assert data["size_code"] in _SIZE_CODES
    assert data["protection_tier_code"] in _TIER_CODES
    assert data["proration_method"] in {"CALENDAR_DAY", "FIXED_30"}
    assert data["lifecycle_status"] in _AGREEMENT_LIFECYCLE
    assert data["billing_status"] in _BILLING_STATUS
    assert isinstance(data["declared_value_cents"], int) and data["declared_value_cents"] >= 0
    assert isinstance(data["monthly_premium_cents"], int) and data["monthly_premium_cents"] >= 0
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["days_overdue"], int) and data["days_overdue"] >= 0


def assert_container_unit(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in _UNIT_STATUS
    assert data["size_code"] in _SIZE_CODES


def assert_delivery_job(data: dict):
    _assert_common_mutable(data)
    assert data["job_kind"] in {"INITIAL_DELIVERY", "REDELIVERY"}
    assert data["status"] in {"SCHEDULED", "COMPLETED", "CANCELLED"}


def assert_move_order(data: dict):
    _assert_common_mutable(data)
    assert data["move_class"] in {"LOCAL", "LONG_DISTANCE"}
    assert data["status"] in {"SCHEDULED", "IN_TRANSIT", "COMPLETED", "CANCELLED"}
    assert isinstance(data["quoted_cost_cents"], int) and data["quoted_cost_cents"] >= 0


def assert_access_visit(data: dict):
    _assert_common_mutable(data)
    assert data["access_kind"] in {"ON_SITE", "DEPOT_PICKUP"}
    assert data["status"] in {"REQUESTED", "FULFILLED", "CANCELLED"}
    assert isinstance(data["redelivery_required"], bool)


def assert_packing_supply_order(data: dict):
    _assert_common_mutable(data)
    assert data["status"] in {"PLACED", "CANCELLED"}
    for f in ("subtotal_cents", "tax_cents", "total_cents"):
        assert isinstance(data[f], int) and data[f] >= 0
    assert data["total_cents"] == data["subtotal_cents"] + data["tax_cents"]


def assert_charge(data: dict):
    _assert_common_mutable(data)
    assert data["charge_type"] in _CHARGE_TYPES
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["settled"], bool)
