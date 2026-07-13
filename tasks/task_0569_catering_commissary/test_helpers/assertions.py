"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_ingredient(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["unit"] in ("GRAM", "ML", "EACH")
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] > 0
    assert data["on_hand_qty"] >= 0
    assert data["committed_qty"] >= 0


def assert_ingredient_conserved(data: dict, expected_total):
    """on_hand_qty + committed_qty is a conserved invariant (PRD Section 3.1)."""
    total = data["on_hand_qty"] + data["committed_qty"]
    assert total == expected_total, (
        f"on_hand+committed must be conserved at {expected_total}, got {total}"
    )


def assert_menu_item(data: dict):
    _assert_common(data)
    assert data["category"] in ("ENTREE", "SIDE", "BEVERAGE", "DESSERT")
    assert isinstance(data["sell_price_cents_per_portion"], int)
    assert isinstance(data["portion_food_cost_cents"], int)


def assert_recipe_line(data: dict):
    """RecipeLine is immutable: carries only id + created_at (PRD Section 2.4)."""
    _assert_common(data)
    assert "version" not in data, "RecipeLine must not expose a version field"
    assert "updated_at" not in data, "RecipeLine must not expose an updated_at field"


def assert_event_order(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "QUOTED", "CONFIRMED", "IN_PRODUCTION", "PACKED",
        "DISPATCHED", "COMPLETED", "ACTUALIZED", "CANCELLED",
    )
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["guest_count"], int)


def assert_order_line(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_quote(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_production_run(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "DONE", "CANCELLED")


def assert_rental_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_staff_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("OFFERED", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED")
