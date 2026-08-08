"""Entity assertions and domain invariant checkers for the Mobile Fuel Delivery API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version for full resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_lightweight_fields(data: dict):
    """id + created_at only; no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "lightweight records omit updated_at"
    assert "version" not in data, "lightweight records omit version"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert data["customer_type"] in ("INDIVIDUAL", "FLEET")
    assert data["status"] == "ACTIVE"


def assert_membership(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "PAUSED", "PAST_DUE", "CANCELLED")


def assert_fleet_account(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_vehicle(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED", "ROUTED", "EN_ROUTE", "ARRIVED",
        "DELIVERED", "UNABLE_TO_ACCESS", "CANCELLED",
    )
    assert data["fuel_type"] in ("REGULAR", "PREMIUM", "DIESEL")


def assert_vehicle_budget_conservation(vehicle: dict):
    """PRD §2.7: committed + settled + remaining == monthly_spend_cap (cap > 0)."""
    cap = vehicle["monthly_spend_cap_cents"]
    if cap > 0:
        assert vehicle["committed_spend_cents"] >= 0
        assert vehicle["settled_spend_cents"] >= 0
        assert (
            vehicle["committed_spend_cents"]
            + vehicle["settled_spend_cents"]
            + vehicle["remaining_budget_cents"]
            == cap
        ), "vehicle budget triad must sum to the spend cap"


def assert_fleet_budget_conservation(fleet: dict):
    """PRD §2.7: committed + settled + remaining == monthly_budget_cap."""
    assert fleet["committed_budget_cents"] >= 0
    assert fleet["settled_budget_cents"] >= 0
    assert (
        fleet["committed_budget_cents"]
        + fleet["settled_budget_cents"]
        + fleet["remaining_budget_cents"]
        == fleet["monthly_budget_cap_cents"]
    ), "fleet budget triad must sum to the budget cap"


def assert_compartment_conservation(comp: dict):
    """PRD §2.7: gallons_reserved + gallons_available == gallons_onboard, both >= 0."""
    assert comp["gallons_reserved"] >= 0
    assert comp["gallons_available"] >= 0
    assert (
        comp["gallons_reserved"] + comp["gallons_available"] == comp["gallons_onboard"]
    ), "compartment gallon triad must reconcile"
