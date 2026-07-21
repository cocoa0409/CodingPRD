"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["loyalty_ledger"], list)
    assert isinstance(data["loyalty_points_balance"], int)
    assert data["loyalty_points_balance"] >= 0, "loyalty_points_balance never below 0"
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["lifetime_spend_cents"], int)


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in ("ROD", "REEL", "TERMINAL_TACKLE", "APPAREL", "DRY_BAIT")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["stock_qty"], int) and data["stock_qty"] >= 0
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["is_special_order_eligible"], bool)


def assert_license(data: dict):
    _assert_common(data)
    assert data["license_type"] in ("RESIDENT_ANNUAL", "NONRESIDENT_ANNUAL", "ONE_DAY", "SENIOR")
    assert isinstance(data["price_cents"], int)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "EXPIRED", "VOID")
    assert isinstance(data["is_voided"], bool)


def assert_bait_tank(data: dict):
    _assert_common(data)
    assert data["species"] in ("MINNOW", "SHINER", "NIGHTCRAWLER", "SHRIMP")
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] > 0
    assert isinstance(data["batches"], list)
    assert isinstance(data["sold_count"], int) and data["sold_count"] >= 0
    assert isinstance(data["available_count"], int) and data["available_count"] >= 0
    assert data["status"] in ("EMPTY", "LOW", "HEALTHY")


def assert_guide(data: dict):
    _assert_common(data)
    assert isinstance(data["half_day_rate_cents"], int)
    assert isinstance(data["full_day_rate_cents"], int)
    assert isinstance(data["max_party_size"], int) and data["max_party_size"] >= 1
    assert data["status"] in ("AVAILABLE", "SUSPENDED")


def assert_venue(data: dict):
    _assert_common(data)
    assert data["water_type"] in ("LAKE", "RIVER", "SALTWATER", "POND")


def assert_charter_booking(data: dict):
    _assert_common(data)
    assert data["trip_type"] in ("HALF_DAY", "FULL_DAY")
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    assert data["status"] in ("REQUESTED", "QUOTED", "CONFIRMED", "COMPLETED", "CANCELLED")


def assert_tournament(data: dict):
    _assert_common(data)
    assert isinstance(data["max_entries"], int) and data["max_entries"] > 0
    assert data["status"] in ("SCHEDULED", "REGISTRATION_OPEN", "IN_PROGRESS", "FINALIZED", "CANCELLED")
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 0


def assert_tournament_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ("REGISTERED", "WEIGHED", "PLACED")
    assert isinstance(data["weigh_ins"], list)
    assert isinstance(data["bag_weight_grams"], int)
    assert isinstance(data["big_fish_grams"], int)


def assert_service_order(data: dict):
    _assert_common(data)
    assert data["service_type"] in ("SPOOLING", "REEL_SERVICE", "ROD_REPAIR", "GUIDE_LINE")
    assert data["status"] in ("RECEIVED", "IN_PROGRESS", "AWAITING_PARTS", "READY", "PICKED_UP", "CANCELLED")


def assert_special_order(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["deposit_cents"], int)
    assert data["status"] in ("REQUESTED", "ORDERED", "ARRIVED", "FULFILLED", "CANCELLED")


def assert_sale(data: dict):
    _assert_common(data)
    assert isinstance(data["lines"], list)
    assert data["status"] in ("OPEN", "COMPLETED", "SETTLED", "REFUNDED", "VOIDED")
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_ledger_balance_consistent(customer: dict):
    """The loyalty_points_balance equals the sum of all ledger deltas (PRD 2.9)."""
    total = sum(entry.get("delta_points", 0) for entry in customer.get("loyalty_ledger", []))
    assert customer["loyalty_points_balance"] == total, (
        f"balance {customer['loyalty_points_balance']} != sum(ledger deltas) {total}"
    )
