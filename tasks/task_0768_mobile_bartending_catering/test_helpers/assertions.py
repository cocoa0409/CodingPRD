"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Field names are PRD-exact.
Append-only Payment records carry only id + created_at (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_state_code"], str)


def assert_package(data: dict):
    _assert_common(data)
    assert data["tier"] in ["BEER_WINE", "CLASSIC", "PREMIUM", "LUXURY"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["included_guest_count"], int) and data["included_guest_count"] >= 1
    assert isinstance(data["guests_per_bartender"], int) and data["guests_per_bartender"] >= 1
    assert isinstance(data["is_active"], bool)


def assert_bartender(data: dict):
    _assert_common(data)
    assert data["availability_status"] in ["AVAILABLE", "ENGAGED", "INACTIVE"]
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert 0 <= data["reliability_score_strict"] <= 100
    assert 0 <= data["reliability_score_lenient"] <= 100
    assert isinstance(data["upcoming_assignment_count"], int) and data["upcoming_assignment_count"] >= 0


def assert_bar_kit(data: dict):
    _assert_common(data)
    assert data["station_type"] in ["BEER_WINE", "FULL_BAR", "MOBILE_CART"]
    assert data["status"] in ["AVAILABLE", "RETIRED"]
    assert isinstance(data["glassware_count"], int) and data["glassware_count"] >= 0


def assert_event(data: dict):
    _assert_common(data)
    assert data["booking_status"] in [
        "DRAFT", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CLOSED", "CANCELLED"
    ]
    assert data["payment_status"] in [
        "UNPAID", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED", "SETTLED"
    ]
    assert data["compliance_posture"] in ["PENDING", "CLEARED", "BLOCKED"]
    assert isinstance(data["guest_count"], int) and data["guest_count"] >= 1
    assert isinstance(data["billable_hours"], int) and data["billable_hours"] >= 1
    assert isinstance(data["required_bartender_count"], int) and data["required_bartender_count"] >= 1


def assert_event_money_nonnegative(data: dict):
    """Financial invariants that hold on any event read."""
    for field in ("subtotal_cents", "service_fee_cents", "gratuity_cents",
                  "provisional_grand_total_cents", "final_grand_total_cents",
                  "deposit_due_cents", "amount_paid_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
        assert data[field] >= 0, f"{field} must be non-negative"


def assert_compliance_review(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "CLEARED", "CHANGES_REQUESTED"]
    assert data["abc_model"] in ["HOST_NO_SALE", "CASH_BAR", "NONE"]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "PROPOSED", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"
    ]
    assert data["role_on_event"] in ["LEAD", "BACK"]
    assert isinstance(data["labor_cost_cents"], int) and data["labor_cost_cents"] >= 0


def assert_kit_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ["RESERVED", "DEPLOYED", "RETURNED", "RELEASED"]


def assert_inventory_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ["GENERATED", "STALE"]
    for field in ("total_servings", "beer_units", "wine_bottles",
                  "spirit_bottles", "ice_lbs", "glassware_needed"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_menu_item(data: dict):
    _assert_common(data)
    assert data["drink_type"] in ["BEER", "WINE", "COCKTAIL", "MOCKTAIL"]


def assert_payment(data: dict):
    """Payment is an immutable ledger record: id + created_at ONLY."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["payment_type"] in [
        "DEPOSIT", "BALANCE", "REFUND", "CANCELLATION_FEE", "BREAKAGE_CHARGE"
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_breakage_report(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SETTLED"]
    assert isinstance(data["items_broken"], int) and data["items_broken"] >= 0
    assert isinstance(data["items_returned"], int) and data["items_returned"] >= 0
