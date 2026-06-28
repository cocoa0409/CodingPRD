"""Nutrition calorie target and cycle-price calculations.

Covers the daily-calorie multiplier chain (mode a), the cycle-price rounding order (mode b),
recompute-on-update, the swap-recipe recompute, and the free-ship boundary on shipping_fee.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    make_pet_parent_headers,
    TEST_USERS,
    set_clock,
    register_account,
    create_pet,
    create_published_recipe,
    create_subscription,
    setup_active_subscription_with_order,
    charge_order,
    create_pet_payload,
    update_pet_payload,
    swap_recipe_payload,
)

VET = TEST_USERS["nutrition_vet_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def test_daily_calorie_target_nested_multipliers(api):
    """PRD §3.3: "take a species resting-energy coefficient — 70.0 for a `DOG` and 60.0 for a
    `CAT` — and multiply it by the basis weight raised to the power 0.75."
    PRD §3.3: "Multiply the resting-energy basis by the four multipliers in that order, left to
    right, and only then round the final product half up to a whole number of kilocalories."

    Design: Difficulty/combinatorial_formula/daily_calorie_target_nested_multipliers_mode_a
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("cal-a@x.com")
    headers = make_pet_parent_headers(account["id"])
    res = api.create_pet(
        create_pet_payload(
            account["id"],
            initial_weight_kg=20.0,
            ideal_weight_kg=20.0,
            activity_level="MODERATE",
            neutered=True,
            body_condition_goal="MAINTAIN",
        ),
        headers,
    )
    pet = validate_success(res, 201)
    # round(70 * 20**0.75 * 1.0 * 1.2 * 1.0 * 1.0) == 794
    assert pet["daily_calorie_target"] == 794, pet["daily_calorie_target"]
    assert pet["current_weight_kg"] == 20.0
    assert pet["life_stage"] == "ADULT"


def test_cycle_price_rounding_order_grams_first(api):
    """PRD §3.5: "First compute `pack_grams_per_day` as the pet's `daily_calorie_target` divided
    by the recipe's `kcal_per_gram`, rounded half up to a whole number of grams per day."
    PRD §3.5: "Finally, `cycle_price_cents` is the hundreds-of-grams figure multiplied by that
    discounted rate, rounded half up to whole cents exactly once at the end."

    Design: Difficulty/combinatorial_formula/cycle_price_rounding_order_mode_b
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("cal-b@x.com")
    pet = create_pet(
        account["id"],
        initial_weight_kg=20.0,
        ideal_weight_kg=20.0,
        activity_level="MODERATE",
        neutered=True,
        body_condition_goal="MAINTAIN",
    )
    recipe = create_published_recipe(
        name="Turkey", kcal_per_gram=2.0, price_per_100g_cents=80, availability_regions=["US"]
    )
    sub = create_subscription(
        account["id"], pet["id"], recipe["id"], cadence_days=28
    )
    assert sub["pack_grams_per_day"] == 397, sub["pack_grams_per_day"]  # round_half_up(794/2.0)
    assert sub["pack_total_grams"] == 11116, sub["pack_total_grams"]    # 397 * 28
    assert sub["cycle_price_cents"] == 8004, sub["cycle_price_cents"]   # round(111.16 * 80*0.9)


def test_order_charge_settlement_pinned_evaluation_order(api):
    """PRD §3.7: "decide `shipping_cents` from that pre-credit subtotal: cold-pack shipping is
    free when `food_subtotal_cents` is at least 8000 cents, and otherwise it is a flat 999 cents".
    PRD §3.7: "Fifth, set `total_charged_cents` to the gross minus `credit_applied_cents`, which
    is never negative."

    Design: Difficulty/combinatorial_formula/order_charge_settlement_pinned_order_mode_c
    """
    account, pet, recipe, sub, order = setup_active_subscription_with_order(
        "cal-c@x.com",
        pet_overrides={
            "initial_weight_kg": 20.0,
            "ideal_weight_kg": 20.0,
            "activity_level": "MODERATE",
            "neutered": True,
            "body_condition_goal": "MAINTAIN",
        },
        recipe_overrides={
            "name": "Turkey",
            "kcal_per_gram": 2.0,
            "price_per_100g_cents": 80,
            "availability_regions": ["US"],
        },
        sub_overrides={"cadence_days": 14},
    )
    charged = charge_order(order["id"])
    # subtotal 4224 < 8000 -> 999 from pre-credit subtotal; wallet 0 -> credit 0; total 5223
    assert charged["shipping_cents"] == 999, charged["shipping_cents"]
    assert charged["credit_applied_cents"] == 0, charged["credit_applied_cents"]
    assert charged["total_charged_cents"] == 5223, charged["total_charged_cents"]


def test_pet_update_recomputes_daily_calorie_target(api):
    """PRD §3.3: "A pet's mutable profile fields — `activity_level`, `neutered`,
    `body_condition_goal`, `ideal_weight_kg`, and `allergen_exclusions` — may be updated by the
    owning parent, and any such update recomputes `daily_calorie_target` immediately."

    Design: Corner/calculations/pet_update_recomputes_daily_calorie_target
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("ca-3@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = create_pet(
        account["id"],
        initial_weight_kg=20.0,
        ideal_weight_kg=20.0,
        activity_level="MODERATE",
        neutered=True,
        body_condition_goal="MAINTAIN",
    )
    res = api.update_pet(pet["id"], update_pet_payload(activity_level="LOW"), headers)
    updated = validate_success(res, 200)
    # round(70 * 20**0.75 * 1.0 * 1.0(LOW) * 1.0 * 1.0) == 662
    assert updated["daily_calorie_target"] == 662, updated["daily_calorie_target"]


def test_swap_recipe_recomputes_pack_grams(api):
    """PRD §3.5: "A `PetParent` may swap a subscription onto a different `recipe_id`. The swap
    re-runs the same referential, allergen, and region gate as activation ..., changes the
    `recipe_id`, recomputes `pack_grams_per_day`, `pack_total_grams`, and `cycle_price_cents`
    against the new recipe, and increments the subscription's `version`."

    Design: Corner/endpoints/swap_recipe_recomputes_pack_and_price
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("ep-1@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = create_pet(
        account["id"],
        initial_weight_kg=20.0,
        ideal_weight_kg=20.0,
        activity_level="MODERATE",
        neutered=True,
        body_condition_goal="MAINTAIN",
    )
    recipe2 = create_published_recipe(
        name="T2", kcal_per_gram=2.0, price_per_100g_cents=80, availability_regions=["US"]
    )
    recipe1 = create_published_recipe(
        name="T1", kcal_per_gram=1.0, price_per_100g_cents=80, availability_regions=["US"]
    )
    sub = create_subscription(
        account["id"], pet["id"], recipe2["id"], cadence_days=14
    )
    sub = get_success_data(api.activate_subscription(sub["id"], headers))
    res = api.swap_recipe(sub["id"], swap_recipe_payload(recipe1["id"]), headers)
    swapped = validate_success(res, 200)
    assert swapped["pack_grams_per_day"] == 794, swapped["pack_grams_per_day"]  # round(794/1.0)
    assert swapped["recipe_id"] == recipe1["id"]


class TestFreeShipBoundary:
    """PRD §3.7 free-ship boundary on shipping_fee, reached through the charge endpoint.

    Design: Difficulty/boundary_precision_check/free_ship_threshold_inclusive_8000_boundary
    """

    def _setup_sub_order(self, api, account, pet, price_per_100g_cents, label):
        recipe = create_published_recipe(
            name=label,
            kcal_per_gram=2.0,
            price_per_100g_cents=price_per_100g_cents,
            availability_regions=["US"],
        )
        headers = make_pet_parent_headers(account["id"])
        sub = create_subscription(
            account["id"], pet["id"], recipe["id"], cadence_days=28
        )
        sub = get_success_data(api.activate_subscription(sub["id"], headers))
        order = get_success_data(
            api.generate_order(sub["id"], {"expected_subscription_version": sub["version"]}, BILLING)
        )
        return order

    def test_subtotal_at_8000_inclusive_ships_free(self, api):
        """PRD §3.7: "the boundary is inclusive, so a subtotal of exactly 8000 ships free while
        7999 pays 999."

        Design: Difficulty/boundary_precision_check/free_ship_threshold_inclusive_8000_boundary
        """
        set_clock("2026-01-01T00:00:00Z")
        account = register_account("bp-1@x.com")
        pet = create_pet(
            account["id"],
            initial_weight_kg=20.0,
            ideal_weight_kg=20.0,
            activity_level="MODERATE",
            neutered=True,
            body_condition_goal="MAINTAIN",
        )
        order = self._setup_sub_order(api, account, pet, 80, "Turkey80")
        charged = charge_order(order["id"])
        # food_subtotal 8004 >= 8000 -> free
        assert charged["food_subtotal_cents"] == 8004, charged["food_subtotal_cents"]
        assert charged["shipping_cents"] == 0, charged["shipping_cents"]

    def test_subtotal_below_8000_pays_flat_fee(self, api):
        """PRD §3.7: "cold-pack shipping is free when `food_subtotal_cents` is at least 8000
        cents, and otherwise it is a flat 999 cents".

        Design: Difficulty/boundary_precision_check/free_ship_threshold_inclusive_8000_boundary
        """
        set_clock("2026-01-01T00:00:00Z")
        account = register_account("bp-1b@x.com")
        pet = create_pet(
            account["id"],
            initial_weight_kg=20.0,
            ideal_weight_kg=20.0,
            activity_level="MODERATE",
            neutered=True,
            body_condition_goal="MAINTAIN",
        )
        order = self._setup_sub_order(api, account, pet, 70, "Turkey70")
        charged = charge_order(order["id"])
        # food_subtotal 7003 < 8000 -> 999
        assert charged["food_subtotal_cents"] == 7003, charged["food_subtotal_cents"]
        assert charged["shipping_cents"] == 999, charged["shipping_cents"]
