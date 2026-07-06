"""Entity assertions and domain invariant checkers.

Assertions validate only fields the PRD guarantees on the response envelope. Computed
figures whose exact value depends on a workflow (food_cost_pct, satisfaction_avg, etc.)
are asserted in individual tests, not forced here.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (§2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_append_only(data: dict):
    """id + created_at ONLY; no updated_at, no version (§2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_client_site(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["cost_status"] in ("ON_TARGET", "OVER_TARGET")
    assert isinstance(data["period_food_cost_cents"], int)
    assert isinstance(data["period_revenue_cents"], int)
    assert isinstance(data["inventory_value_cents"], int)
    # food_cost_pct and satisfaction_avg may be null.
    assert data.get("food_cost_pct") is None or isinstance(data["food_cost_pct"], (int, float))
    assert data.get("satisfaction_avg") is None or isinstance(data["satisfaction_avg"], (int, float))


def assert_employee(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert isinstance(data["wallet_balance_cents"], int)
    assert isinstance(data["daily_subsidy_used_cents"], int)
    assert isinstance(data.get("restricted_allergens", []), list)


def assert_menu_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PUBLISHED")


def assert_menu_item(data: dict):
    _assert_common(data)
    assert data["category"] in ("ENTREE", "SIDE", "BEVERAGE", "DESSERT", "HEALTHY")
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["standard_recipe_cost_cents"], int)


def assert_catering_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_service_session(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "FORECAST_LOCKED", "IN_SERVICE", "CLOSED", "CANCELLED")
    assert data["meal_period"] in ("BREAKFAST", "LUNCH", "DINNER")
    assert isinstance(data["actual_headcount"], int)
    assert isinstance(data["revenue_cents"], int)
    assert isinstance(data["theoretical_food_cost_cents"], int)


def assert_badge_transaction(data: dict):
    _assert_common(data)
    assert data["status"] in ("COMPLETED", "VOIDED")
    assert data["payment_method"] in ("BADGE_PAYROLL", "WALLET")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["subsidy_applied_cents"], int)
    assert isinstance(data["employee_charge_cents"], int)


def assert_vendor(data: dict):
    _assert_common(data)
    assert data["category"] in ("PRODUCE", "PROTEIN", "DRY_GOODS", "BEVERAGE", "DISPOSABLES")


def assert_purchase_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "RECEIVED", "CANCELLED")
    assert isinstance(data["total_cents"], int)


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "DEPLETED")
    assert isinstance(data["qty_on_hand"], int)
    assert isinstance(data["qty_reserved"], int)
    assert isinstance(data["unit_cost_cents"], int)


def assert_catering_order(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "APPROVED", "REVISION_REQUESTED",
        "CONFIRMED", "FULFILLED", "INVOICED", "CANCELLED",
    )
    assert isinstance(data["headcount"], int) and data["headcount"] >= 1


def assert_vendor_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECEIVED", "MATCHED", "APPROVED", "DISPUTED", "PAID")
    assert isinstance(data["invoiced_amount_cents"], int)


def assert_waste_event(data: dict):
    _assert_append_only(data)
    assert isinstance(data["cost_cents"], int)
    # Append-only: must NOT carry version.
    assert "version" not in data, "WasteEvent is append-only and carries no version"


def assert_satisfaction_survey(data: dict):
    _assert_append_only(data)
    assert 1 <= data["rating"] <= 5
    assert "version" not in data, "SatisfactionSurvey is append-only and carries no version"
