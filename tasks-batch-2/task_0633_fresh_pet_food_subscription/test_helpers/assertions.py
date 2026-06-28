"""Entity assertions and domain invariant checkers.

Each ``assert_{entity}`` validates the response shape against the PRD contract using the
framework's generic format checkers. Domain invariant helpers verify cross-field rules that
must hold after any operation (e.g. the billing waterfall conserves the gross).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version present (for common_fields: true resources)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str)
    assert data["country_code"] in ("US", "CA")
    assert isinstance(data["referral_code"], str) and len(data["referral_code"]) == 8
    assert data["referral_code"] == data["referral_code"].upper()
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents is never negative"
    assert isinstance(data["lifetime_referral_grants_cents"], int)
    assert data["lifetime_referral_grants_cents"] >= 0
    assert data["status"] == "ACTIVE"


def assert_pet(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["name"], str)
    assert data["species"] in ("DOG", "CAT")
    assert data["sex"] in ("MALE", "FEMALE")
    assert isinstance(data["current_weight_kg"], (int, float))
    assert data["current_weight_kg"] > 0
    assert data["activity_level"] in ("LOW", "MODERATE", "HIGH")
    assert isinstance(data["neutered"], bool)
    assert data["body_condition_goal"] in ("LOSE", "MAINTAIN", "GAIN")
    assert isinstance(data["allergen_exclusions"], list)
    assert isinstance(data["daily_calorie_target"], (int, float))
    assert data["daily_calorie_target"] > 0
    assert data["life_stage"] in ("PUPPY_KITTEN", "ADULT", "SENIOR")
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_recipe(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["species"] in ("DOG", "CAT")
    assert data["kcal_per_gram"] > 0
    assert isinstance(data["price_per_100g_cents"], int) and data["price_per_100g_cents"] > 0
    assert isinstance(data["ingredient_allergens"], list)
    assert isinstance(data["availability_regions"], list)
    assert isinstance(data["vet_formulated"], bool)
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_subscription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["pet_id"])
    assert is_valid_uuid(data["recipe_id"])
    assert data["cadence_days"] in (14, 21, 28)
    assert isinstance(data["transition_remaining_cycles"], int)
    assert data["transition_remaining_cycles"] >= 0
    assert isinstance(data["consecutive_failed_charges"], int)
    assert data["consecutive_failed_charges"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "PAST_DUE", "CANCELLED")


def assert_weight_log(data: dict):
    """WeightLog is append-only: id + created_at only; NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "WeightLog must not carry updated_at"
    assert "version" not in data, "WeightLog must not carry version"
    assert is_valid_uuid(data["pet_id"])
    assert data["weight_kg"] > 0
    assert data["status"] in ("APPLIED", "SUPERSEDED")


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["subscription_id"])
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert isinstance(data["food_grams"], (int, float))
    assert isinstance(data["is_transition_cycle"], bool)
    assert isinstance(data["food_subtotal_cents"], int)
    assert data["status"] in ("SCHEDULED", "SKIPPED", "CHARGING", "PAID", "FAILED")


def assert_shipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["coolant_packs"], int) and data["coolant_packs"] >= 1
    assert isinstance(data["transit_days"], int)
    assert 1 <= data["transit_days"] <= 5
    assert data["status"] in ("PENDING", "DISPATCHED", "DELIVERED", "SPOILED")


def assert_referral_credit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["referrer_account_id"])
    assert is_valid_uuid(data["referred_account_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["beneficiary"] in ("REFERRER", "REFERRED")
    assert data["reason"] in ("SIGNUP", "MAKE_GOOD")
    assert data["status"] in ("PENDING", "GRANTED", "REVOKED")


# --------------------------------------------------------------------------- #
# Domain invariants                                                           #
# --------------------------------------------------------------------------- #
def assert_settlement_conserves_gross(order: dict):
    """PRD §3.7 billing waterfall: total_charged + credit_applied == food_subtotal + shipping,
    and total_charged is never negative."""
    gross = order["food_subtotal_cents"] + order["shipping_cents"]
    assert order["total_charged_cents"] + order["credit_applied_cents"] == gross, (
        "total_charged_cents + credit_applied_cents must reconstitute the gross "
        f"(got {order['total_charged_cents']} + {order['credit_applied_cents']} != {gross})"
    )
    assert order["total_charged_cents"] >= 0, "total_charged_cents is never negative"
    assert order["credit_applied_cents"] >= 0
