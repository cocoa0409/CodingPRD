"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_client(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CANCELLED")
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert data["billing_mode"] in ("PER_WEEK", "PER_MEAL")
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1


def assert_chef(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_dietary_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_weekly_menu(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "PROPOSED", "APPROVED", "SKIPPED", "COOKED", "CANCELLED"
    )
    assert isinstance(data["grocery_cost_cents"], int) and data["grocery_cost_cents"] >= 0


def assert_menu_meal(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "COOKED", "CANCELLED")
    assert isinstance(data["meal_grocery_cost_cents"], int)
    assert data["meal_slot"] in ("BREAKFAST", "LUNCH", "DINNER")


def assert_cook_session(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "NO_SHOW", "CANCELLED"
    )
    assert isinstance(data["provisional_payout_cents"], int)


def assert_container(data: dict):
    _assert_common(data)
    assert data["status"] == "FILLED"
    assert isinstance(data["portion_count"], int) and data["portion_count"] >= 1


def assert_billing_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "PAID")
    assert isinstance(data["gross_amount_cents"], int)
