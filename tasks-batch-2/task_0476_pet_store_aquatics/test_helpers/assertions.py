"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["loyalty_point_value_cents"], int)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in ("FOOD", "HABITAT", "ACCESSORY", "MEDICATION")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] > 0
    assert isinstance(data["is_prescription_diet"], bool)
    assert isinstance(data["loyalty_points_per_unit"], int)
    assert data["recall_state"] in ("CLEAR", "RECALLED")


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0
    assert isinstance(data["quantity_reserved"], int) and data["quantity_reserved"] >= 0
    assert data["quantity_reserved"] <= data["quantity_on_hand"]
    assert data["status"] in ("AVAILABLE", "QUARANTINED", "DEPLETED")


def assert_livestock_batch(data: dict):
    _assert_common(data)
    assert data["animal_class"] in ("FISH", "REPTILE", "SMALL_ANIMAL")
    assert isinstance(data["head_count"], int) and data["head_count"] > 0
    assert isinstance(data["mortality_count"], int) and data["mortality_count"] >= 0
    assert data["mortality_count"] <= data["head_count"]
    assert data["health_state"] in (
        "QUARANTINE", "HEALTHY", "UNDER_TREATMENT", "CONDEMNED"
    )
    assert data["sale_state"] in ("HELD", "ON_FLOOR", "RESERVED", "SOLD_OUT")


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["loyalty_points"], int) and data["loyalty_points"] >= 0
    assert isinstance(data["lifetime_spend_cents"], int) and \
        data["lifetime_spend_cents"] >= 0
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")


def assert_prescription(data: dict):
    _assert_common(data)
    assert isinstance(data["max_units_per_order"], int) and \
        data["max_units_per_order"] > 0
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_clinic_appointment(data: dict):
    _assert_common(data)
    assert data["service_type"] in ("GROOMING", "VACCINE", "VET_EXAM")
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in (
        "BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"
    )


def assert_subscription(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity_per_cycle"], int) and \
        data["quantity_per_cycle"] > 0
    assert isinstance(data["cycle_days"], int) and data["cycle_days"] > 0
    assert isinstance(data["shipments_count"], int) and data["shipments_count"] >= 0
    assert data["status"] in ("ACTIVE", "PAUSED", "HALTED", "CANCELLED")


def assert_shipment(data: dict):
    _assert_common(data)
    assert isinstance(data["units"], int) and data["units"] > 0
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert data["status"] == "FULFILLED"


def assert_special_order(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert data["status"] in ("REQUESTED", "ALLOCATED", "FULFILLED", "CANCELLED")


def assert_recall(data: dict):
    _assert_common(data)
    assert data["severity"] in ("ADVISORY", "MANDATORY")
    assert isinstance(data["affected_lot_count"], int) and \
        data["affected_lot_count"] >= 0
    assert isinstance(data["halted_subscription_count"], int) and \
        data["halted_subscription_count"] >= 0
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_adoption_event(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["placed_head"], int) and data["placed_head"] >= 0
    assert data["placed_head"] <= data["capacity"]
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED")


def assert_adoption_placement(data: dict):
    _assert_common(data)
    assert isinstance(data["head"], int) and data["head"] > 0
    assert data["status"] in ("PLACED", "RETURNED")
