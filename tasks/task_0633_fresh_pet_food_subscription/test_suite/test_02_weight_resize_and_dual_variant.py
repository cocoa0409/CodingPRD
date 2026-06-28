"""Weight logging, the resize cascade, and the estimate-vs-actual dual-variant divergence."""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    make_pet_parent_headers,
    TEST_USERS,
    set_clock,
    register_account,
    create_pet,
    create_published_recipe,
    create_subscription,
    record_weight,
    generate_order,
    resize_payload,
)

BILLING = TEST_USERS["billing_admin_headers"]


def test_estimate_vs_actual_diverge_after_same_cycle_resize(api):
    """PRD §3.5: "The **estimate** variant of this calculation uses the pet's live
    `daily_calorie_target`, is not snapshotted, and is recomputed onto `cycle_price_cents` on
    every resize realization and every recipe swap."
    PRD §3.5: "The **actual** variant of the same formula is frozen onto an order at generation
    (see §3.6); a later weight change does not retro-price an order that has already been
    generated."

    Design: Difficulty/dual_variant_calc/cycle_price_estimate_vs_actual_snapshot_diverge_on_weight_change
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("dv1@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = create_pet(
        account["id"],
        initial_weight_kg=10.0,
        ideal_weight_kg=10.0,
        activity_level="MODERATE",
        neutered=True,
        body_condition_goal="MAINTAIN",
    )
    recipe = create_published_recipe(
        name="Beef", kcal_per_gram=2.0, price_per_100g_cents=120, availability_regions=["US"]
    )
    sub = create_subscription(account["id"], pet["id"], recipe["id"], cadence_days=14)
    sub = get_success_data(api.activate_subscription(sub["id"], headers))
    order = generate_order(sub["id"], sub["version"])

    sub_now = get_success_data(api.get_subscription(sub["id"], headers))
    record_weight(account["id"], pet["id"], 15.0, effective_date="2026-01-01T00:00:00Z")

    resized = validate_success(
        api.resize_subscription(sub["id"], resize_payload(sub_now["version"]), headers), 200
    )
    # 15kg: dct 640 -> g/day 320, total 4480, disc .05, round(44.8 * 114) == 5107
    assert resized["cycle_price_cents"] == 5107, resized["cycle_price_cents"]

    order_after = get_success_data(api.get_order(order["id"], headers))
    # frozen at the 10kg snapshot: dct 472 -> g/day 236, total 3304, disc 0 -> 3965
    assert order_after["food_subtotal_cents"] == 3965, order_after["food_subtotal_cents"]
    assert resized["cycle_price_cents"] != order_after["food_subtotal_cents"]


def test_latest_effective_date_weight_log_supersedes(api):
    """PRD §3.4: "Among all of a pet's logs, exactly one is `APPLIED`: the one with the latest
    `effective_date`, breaking ties by the earlier `created_at` (ascending). Every other log is
    `SUPERSEDED`."
    PRD §3.4: "then recomputes the pet's `current_weight_kg` from the `APPLIED` log and recomputes
    `daily_calorie_target` as a cascade."

    Design: Difficulty/resource_temporal_overlap/weight_log_latest_effective_date_supersedes
    """
    set_clock("2026-01-15T00:00:00Z")
    account = register_account("to-1@x.com")
    headers = make_pet_parent_headers(account["id"])
    pet = create_pet(
        account["id"],
        initial_weight_kg=20.0,
        ideal_weight_kg=20.0,
        activity_level="MODERATE",
        neutered=True,
        body_condition_goal="MAINTAIN",
    )
    wl1 = record_weight(account["id"], pet["id"], 20.0, effective_date="2026-01-05T00:00:00Z")
    wl2 = record_weight(account["id"], pet["id"], 24.0, effective_date="2026-01-10T00:00:00Z")

    wl1_read = get_success_data(api.get_weight_log(wl1["id"], headers))
    wl2_read = get_success_data(api.get_weight_log(wl2["id"], headers))
    assert wl2_read["status"] == "APPLIED", wl2_read["status"]
    assert wl1_read["status"] == "SUPERSEDED", wl1_read["status"]

    pet_after = get_success_data(api.get_pet(pet["id"], headers))
    assert pet_after["current_weight_kg"] == 24.0, pet_after["current_weight_kg"]
    # round(70 * 24**0.75 * 1.0 * 1.2 * 1.0 * 1.0) == 911
    assert pet_after["daily_calorie_target"] == 911, pet_after["daily_calorie_target"]


def test_staged_resize_realized_on_order_generate_after_clock_reaches_effective(api):
    """PRD §3.4: "otherwise it remains staged and is realized later, at order-generation time,
    once the clock has reached the effective instant."
    PRD §3.6: "if a staged resize's `resize_effective_at` is at or before the clock, that resize
    is realized into the pack fields first."

    Design: Corner/cross_cutting_complexity_layers/scheduled_resize_realized_on_order_generate_after_clock_advance
    """
    set_clock("2026-01-01T00:00:00Z")
    account = register_account("cc-3@x.com")
    headers = make_pet_parent_headers(account["id"])
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
    sub = create_subscription(account["id"], pet["id"], recipe["id"], cadence_days=28)
    sub = get_success_data(api.activate_subscription(sub["id"], headers))

    record_weight(account["id"], pet["id"], 24.0, effective_date="2026-01-01T00:00:00Z")
    sub_now = get_success_data(api.get_subscription(sub["id"], headers))
    staged = validate_success(
        api.resize_subscription(
            sub["id"],
            resize_payload(sub_now["version"], effective_at="2026-01-15T00:00:00Z"),
            headers,
        ),
        200,
    )
    # 24kg -> dct 911 -> round_half_up(911/2.0) == 456 grams/day staged
    assert staged["pending_resize_grams_per_day"] == 456, staged["pending_resize_grams_per_day"]

    set_clock("2026-01-20T00:00:00Z")
    sub_gen = get_success_data(api.get_subscription(sub["id"], BILLING))
    order = generate_order(sub["id"], sub_gen["version"])
    # realized: 456 g/day * 28 == 12768
    assert order["food_grams"] == 12768, order["food_grams"]
