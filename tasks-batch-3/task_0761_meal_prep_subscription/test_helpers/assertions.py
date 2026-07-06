"""Entity assertions and domain invariant checkers for the meal-prep subscription API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_mutable_common(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_plan(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert isinstance(data["meals_per_week"], int) and data["meals_per_week"] >= 1
    assert isinstance(data["price_per_meal_cents"], int) and data["price_per_meal_cents"] >= 1


def assert_meal(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["meal_code"], str) and data["meal_code"]
    for macro in ("protein_g", "carb_g", "fat_g", "calories"):
        assert isinstance(data[macro], int) and data[macro] >= 0
    assert isinstance(data["allergens"], list)
    assert isinstance(data["dietary_tags"], list)


def assert_customer(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["allergen_exclusions"], list)
    assert isinstance(data["referral_code"], str) and data["referral_code"]
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents is never negative (PRD §2.5)"
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_subscription(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["plan_id"], str)
    assert isinstance(data["meals_per_week"], int)
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_production_run(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["par_total"], int) and data["par_total"] >= 0
    assert isinstance(data["par_reserved"], int) and data["par_reserved"] >= 0
    assert isinstance(data["par_remaining"], int) and data["par_remaining"] >= 0
    assert data["par_remaining"] == data["par_total"] - data["par_reserved"], (
        "par_remaining must equal par_total - par_reserved (PRD §2.8)"
    )
    assert data["status"] in ("SCHEDULED", "AVAILABLE", "SOLD_OUT", "COMPLETED", "CANCELLED")


def assert_box(data: dict):
    _assert_mutable_common(data)
    assert data["fulfillment_status"] in (
        "OPEN", "LOCKED", "SHIPPED", "DELIVERED", "SKIPPED", "CANCELLED",
    )
    assert data["billing_status"] in (
        "UNCHARGED", "PENDING", "CHARGED", "CHARGE_FAILED", "REFUNDED", "WAIVED",
    )
    assert data["refund_destination"] in ("NONE", "ORIGINAL_PAYMENT", "WALLET_CREDIT")
    assert isinstance(data["is_first_box"], bool)


def assert_box_item(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("SELECTED", "SWAPPED_OUT", "REMOVED")


def assert_referral(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in ("PENDING", "REWARDED", "EXPIRED")
    assert isinstance(data["reward_cents"], int) and data["reward_cents"] >= 0


def assert_credit_ledger(data: dict):
    """Append-only ledger entry: carries only id + created_at (no updated_at, no version)."""
    _assert_common(data)
    assert "updated_at" not in data, "ledger entry is append-only and has no updated_at (PRD §2.4)"
    assert "version" not in data, "ledger entry is append-only and has no version (PRD §2.4)"
    assert data["reason"] in ("REFERRAL_REWARD", "SWAP_CREDIT", "REFUND_CREDIT", "CREDIT_APPLIED")
    assert isinstance(data["amount_cents"], int)


def assert_par_conserved(run: dict):
    """Kitchen-par conservation invariant: par_total == par_reserved + par_remaining (PRD §2.8)."""
    assert run["par_total"] == run["par_reserved"] + run["par_remaining"], (
        f"par conservation violated: {run['par_total']} != "
        f"{run['par_reserved']} + {run['par_remaining']}"
    )
    assert run["par_remaining"] >= 0, "par_remaining is never negative (PRD §2.8)"
