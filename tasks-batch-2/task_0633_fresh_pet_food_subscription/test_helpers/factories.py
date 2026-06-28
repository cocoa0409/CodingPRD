"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying the PRD-declared ``source: input`` fields for a create
call, with sensible defaults. ``**overrides`` lets a test control any field. Required fields
are always present; optional fields (those the PRD marks optional / with a default) are only
included when the caller supplies them, so the server applies its own defaults.
"""

# Canonical numeric defaults reused across the suite.
DEFAULTS = {
    "PET_BIRTH_DATE": "2022-01-01",          # ~4y old at default clock -> ADULT
    "DOG_WEIGHT_KG": 20.0,                    # MAIN pet -> daily_calorie_target 794
    "RECIPE_KCAL_PER_GRAM": 2.0,
    "RECIPE_PRICE_PER_100G_CENTS": 80,        # recipe P80
    "CADENCE_DAYS": 28,
}


def register_account_payload(email, full_name="Test Holder", **overrides) -> dict:
    """POST /api/accounts/register. country_code/referral_code are optional."""
    payload = {"email": email, "full_name": full_name}
    payload.update(overrides)
    return payload


def create_recipe_payload(
    name="Turkey & Sweet Potato",
    species="DOG",
    kcal_per_gram=DEFAULTS["RECIPE_KCAL_PER_GRAM"],
    price_per_100g_cents=DEFAULTS["RECIPE_PRICE_PER_100G_CENTS"],
    **overrides,
) -> dict:
    """POST /api/recipes. ingredient_allergens/availability_regions/vet_formulated optional."""
    payload = {
        "name": name,
        "species": species,
        "kcal_per_gram": kcal_per_gram,
        "price_per_100g_cents": price_per_100g_cents,
    }
    payload.update(overrides)
    return payload


def create_pet_payload(
    account_id,
    name="Bo",
    species="DOG",
    sex="MALE",
    birth_date=DEFAULTS["PET_BIRTH_DATE"],
    initial_weight_kg=DEFAULTS["DOG_WEIGHT_KG"],
    ideal_weight_kg=DEFAULTS["DOG_WEIGHT_KG"],
    **overrides,
) -> dict:
    """POST /api/pets. activity_level/neutered/body_condition_goal/allergen_exclusions optional."""
    payload = {
        "account_id": account_id,
        "name": name,
        "species": species,
        "sex": sex,
        "birth_date": birth_date,
        "initial_weight_kg": initial_weight_kg,
        "ideal_weight_kg": ideal_weight_kg,
    }
    payload.update(overrides)
    return payload


def update_pet_payload(**overrides) -> dict:
    """PATCH /api/pets/{petId}. All fields optional; caller supplies what to change."""
    return dict(overrides)


def create_weight_log_payload(pet_id, weight_kg, **overrides) -> dict:
    """POST /api/weight-logs. effective_date optional (defaults to clock server-side)."""
    payload = {"pet_id": pet_id, "weight_kg": weight_kg}
    payload.update(overrides)
    return payload


def create_subscription_payload(account_id, pet_id, recipe_id, **overrides) -> dict:
    """POST /api/subscriptions. cadence_days optional (defaults to 28 server-side)."""
    payload = {"account_id": account_id, "pet_id": pet_id, "recipe_id": recipe_id}
    payload.update(overrides)
    return payload


def pause_payload(**overrides) -> dict:
    """POST /api/subscriptions/{id}/pause. resume_at optional."""
    return dict(overrides)


def swap_recipe_payload(recipe_id, **overrides) -> dict:
    """POST /api/subscriptions/{id}/swap-recipe."""
    payload = {"recipe_id": recipe_id}
    payload.update(overrides)
    return payload


def resize_payload(expected_subscription_version, **overrides) -> dict:
    """POST /api/subscriptions/{id}/resize. effective_at optional."""
    payload = {"expected_subscription_version": expected_subscription_version}
    payload.update(overrides)
    return payload


def generate_order_payload(expected_subscription_version) -> dict:
    """POST /api/subscriptions/{id}/orders."""
    return {"expected_subscription_version": expected_subscription_version}


def settle_charge_payload(outcome) -> dict:
    """POST /api/orders/{id}/settle-charge. outcome is SUCCEEDED or DECLINED."""
    return {"outcome": outcome}


def update_shipment_payload(transit_days) -> dict:
    """PATCH /api/shipments/{id}."""
    return {"transit_days": transit_days}


def redeem_preview_payload(referral_code) -> dict:
    """POST /api/referrals/redeem-preview."""
    return {"referral_code": referral_code}
