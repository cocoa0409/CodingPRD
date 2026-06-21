"""Production batches: food cost (estimate vs actual), production fee, recipe
publish/revise/retire lifecycle, and batch state guards.

Translates difficulty queue instances:
  dual_variant_calc / batch_estimated_vs_actual_food_cost_diverge
  non_linear_state_machine / recipe_cyclic_revise_loop_bumps_version
  non_linear_state_machine / production_batch_branch_complete_vs_scrap
  cross_entity_state_dependency / batch_plan_requires_recipe_published
and corner queue instances for production-fee rebate, stock-block, allergen
union, recipe-in-use, recipe-empty, retired-terminal, initial-state, and the
order-receipt reconciliation claims.
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_operator_headers, TEST_USERS,
    register_funded_member, register_member, create_ingredient, stock_ingredient,
    create_published_recipe, create_draft_recipe_with_component,
    create_planned_batch, create_started_batch,
)

FM = TEST_USERS["facility_manager_headers"]


# ── Difficulty: dual_variant_calc / batch_estimated_vs_actual_food_cost_diverge ──

def test_batch_estimated_and_actual_food_cost_diverge(api):
    """PRD 3.5: "each line is rounded to whole cents first, and only then are
    the lines summed." PRD 3.7: "Then compute spoilage as the base multiplied by
    the spoilage rate of five percent, rounded to whole cents with round-half-up,
    and add it to the base; the sum is the batch's actual_food_cost_cents."
    Estimate (planned qty, no spoilage) = 3199; actual (actual qty + 5% spoilage)
    = 7065; the two diverge.

    Design: Difficulty/dual_variant_calc/batch_estimated_vs_actual_food_cost_diverge
    """
    member, _ = register_funded_member(amount_cents=1000000, plan_tier="PREMIUM")
    mo = make_member_operator_headers(member["id"])
    ing_a = create_ingredient(name="A", unit_cost_cents=333)
    ing_b = create_ingredient(name="B", unit_cost_cents=1299)
    ing_c = create_ingredient(name="C", unit_cost_cents=845)
    for ing in (ing_a, ing_b, ing_c):
        stock_ingredient(member["id"], ing["id"], 100, ing["unit_cost_cents"])
    recipe = create_published_recipe(
        member["id"], batch_yield_units=40,
        components=[(ing_a["id"], 2.5), (ing_b["id"], 1.333), (ing_c["id"], 0.75)],
        name="R1",
    )
    batch = create_started_batch(member["id"], recipe["id"], planned_yield_units=40)
    assert batch["estimated_food_cost_cents"] == 3199, f"est got {batch['estimated_food_cost_cents']}"

    completed = validate_success(api.complete_batch(member["id"], batch["id"], {
        "actual_yield_units": 40,
        "actual_components": [
            {"ingredient_id": ing_a["id"], "actual_qty": 6.0},
            {"ingredient_id": ing_b["id"], "actual_qty": 2.666},
            {"ingredient_id": ing_c["id"], "actual_qty": 1.5},
        ],
    }, mo), 200)
    assert completed["actual_food_cost_cents"] == 7065, f"act got {completed['actual_food_cost_cents']}"
    assert completed["estimated_food_cost_cents"] != completed["actual_food_cost_cents"]


def test_recipe_publish_estimate_round_per_line_then_sum(api):
    """PRD 3.5: "At recipe publication the scale factor is exactly 1.0, so the
    estimate reflects a single standard batch, and the result is stored in the
    recipe's estimated_food_cost_cents." With the same BOM the published recipe
    estimate is 3199 (round-per-line: 833 + 1732 + 634).

    Design: Difficulty/dual_variant_calc/batch_estimated_vs_actual_food_cost_diverge
    """
    member, _ = register_funded_member(amount_cents=1000000)
    ing_a = create_ingredient(name="A", unit_cost_cents=333)
    ing_b = create_ingredient(name="B", unit_cost_cents=1299)
    ing_c = create_ingredient(name="C", unit_cost_cents=845)
    recipe = create_published_recipe(
        member["id"], batch_yield_units=40,
        components=[(ing_a["id"], 2.5), (ing_b["id"], 1.333), (ing_c["id"], 0.75)],
        name="R1b",
    )
    assert recipe["estimated_food_cost_cents"] == 3199


# ── Corner: calculations / production_fee_volume_rebate_at_threshold ──

def test_production_fee_volume_rebate_at_threshold(api):
    """PRD 3.8: "The base fee is the batch's actual_yield_units multiplied by a
    per-unit facility fee of 35 cents." and "when actual_yield_units is at least
    100, a flat rebate of 500 cents is subtracted from the base fee". Yield 100
    gives base 3500 minus rebate 500 = 3000.

    Design: Corner/calculations/production_fee_volume_rebate_at_threshold
    """
    member, _ = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="PfIng", unit_cost_cents=100)
    stock_ingredient(member["id"], ing["id"], 1000, 100)
    recipe = create_published_recipe(member["id"], batch_yield_units=100,
                                     components=[(ing["id"], 1.0)], name="PfR")
    batch = create_started_batch(member["id"], recipe["id"], planned_yield_units=100)
    completed = validate_success(api.complete_batch(member["id"], batch["id"], {
        "actual_yield_units": 100,
        "actual_components": [{"ingredient_id": ing["id"], "actual_qty": 100.0}],
    }, mo), 200)
    assert completed["production_fee_cents"] == 3000, f"got {completed['production_fee_cents']}"


# ── Difficulty: non_linear_state_machine / production_batch_branch_complete_vs_scrap ──

def test_batch_complete_charges_production_fee(api):
    """PRD 3.6: "Completion computes the actual food cost (see 3.7) and the
    production fee (see 3.8)." With yield 10 and no rebate the production fee is
    10 * 35 = 350 and the batch is COMPLETED.

    Design: Difficulty/non_linear_state_machine/production_batch_branch_complete_vs_scrap
    """
    member, _ = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="Sugar", unit_cost_cents=100)
    stock_ingredient(member["id"], ing["id"], 1000, 100)
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(ing["id"], 1.0)], name="R6c")
    batch = create_started_batch(member["id"], recipe["id"], planned_yield_units=10)
    completed = validate_success(api.complete_batch(member["id"], batch["id"], {
        "actual_yield_units": 10,
        "actual_components": [{"ingredient_id": ing["id"], "actual_qty": 10.0}],
    }, mo), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["production_fee_cents"] == 350, f"got {completed['production_fee_cents']}"


def test_batch_scrap_charges_nothing_and_is_terminal(api):
    """PRD 3.6: "A batch may instead be scrapped, ending in SCRAPPED. ...
    Scrapping levies no wallet charge and consumes no ingredients; the batch
    simply becomes terminal." A scrapped IN_PRODUCTION batch has no production
    fee.

    Design: Difficulty/non_linear_state_machine/production_batch_branch_complete_vs_scrap
    """
    member, _ = register_funded_member(amount_cents=100000)
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="Sugar2", unit_cost_cents=100)
    stock_ingredient(member["id"], ing["id"], 1000, 100)
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(ing["id"], 1.0)], name="R6s")
    batch = create_started_batch(member["id"], recipe["id"], planned_yield_units=10)
    scrapped = validate_success(api.scrap_batch(member["id"], batch["id"], mo), 200)
    assert scrapped["status"] == "SCRAPPED"
    assert scrapped["production_fee_cents"] is None, f"got {scrapped['production_fee_cents']}"


# ── Difficulty: non_linear_state_machine / recipe_cyclic_revise_loop_bumps_version ──

def test_recipe_revise_publish_loop_bumps_version_to_2(api):
    """PRD 3.4: "Revising a PUBLISHED recipe sends it back to DRAFT and increments
    its version by one, so the same recipe may loop DRAFT to PUBLISHED to DRAFT
    repeatedly, each revision producing a new version number." After
    publish/revise/publish the status is PUBLISHED and version is 2.

    Design: Difficulty/non_linear_state_machine/recipe_cyclic_revise_loop_bumps_version
    """
    member = register_member(business_name="M5")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="Flour", unit_cost_cents=200)
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(ing["id"], 1.0)], name="R5")
    validate_success(api.revise_recipe(member["id"], recipe["id"], mo), 200)
    republished = validate_success(api.publish_recipe(member["id"], recipe["id"], mo), 200)
    assert republished["status"] == "PUBLISHED"
    assert republished["version"] == 2, f"got {republished['version']}"


def test_recipe_revise_returns_to_draft(api):
    """PRD 3.4: "Revising a PUBLISHED recipe sends it back to DRAFT and increments
    its version by one". A single revise from PUBLISHED yields status DRAFT and
    version 2.

    Design: Difficulty/non_linear_state_machine/recipe_cyclic_revise_loop_bumps_version
    """
    member = register_member(business_name="M5b")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="Flour2", unit_cost_cents=200)
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(ing["id"], 1.0)], name="R5b")
    revised = validate_success(api.revise_recipe(member["id"], recipe["id"], mo), 200)
    assert revised["status"] == "DRAFT"
    assert revised["version"] == 2


# ── Difficulty: cross_entity_state_dependency / batch_plan_requires_recipe_published ──

def test_batch_plan_against_draft_recipe_rejected(api):
    """PRD 3.6: "Planning requires the acting member to be ACTIVE ... the target
    recipe to be PUBLISHED (otherwise ERR_RECIPE_NOT_PUBLISHED)". A batch planned
    against a still-DRAFT recipe is rejected.

    Design: Difficulty/cross_entity_state_dependency/batch_plan_requires_recipe_published
    """
    member = register_member(business_name="M12")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="Salt", unit_cost_cents=50)
    recipe = create_draft_recipe_with_component(member["id"], ing["id"], planned_qty=1.0,
                                                batch_yield_units=10, name="R12")
    res = api.create_batch(member["id"], {"recipe_id": recipe["id"], "planned_yield_units": 10}, mo)
    validate_error(res, "ERR_RECIPE_NOT_PUBLISHED")


def test_batch_plan_against_published_recipe_succeeds(api):
    """PRD 3.6: "A production batch is a member's run of a published recipe."
    Planning against a PUBLISHED recipe creates a PLANNED batch.

    Design: Difficulty/cross_entity_state_dependency/batch_plan_requires_recipe_published
    """
    member = register_member(business_name="M12b")
    ing = create_ingredient(name="Salt2", unit_cost_cents=50)
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(ing["id"], 1.0)], name="R12b")
    batch = create_planned_batch(member["id"], recipe["id"], planned_yield_units=10)
    assert batch["status"] == "PLANNED"


# ── Corner: state_machines / batch_created_starts_in_planned ──

def test_batch_initial_state_is_planned(api):
    """PRD 3.6: "A batch is created in PLANNED, and its status advances through
    IN_PRODUCTION and then forks to either COMPLETED or SCRAPPED."

    Design: Corner/state_machines/batch_created_starts_in_planned
    """
    member = register_member(business_name="In")
    ing = create_ingredient(name="InIng", unit_cost_cents=100)
    recipe = create_published_recipe(member["id"], batch_yield_units=5,
                                     components=[(ing["id"], 1.0)], name="InR")
    batch = create_planned_batch(member["id"], recipe["id"], planned_yield_units=5)
    assert batch["status"] == "PLANNED"


# ── Corner: state_machines / recipe_publish_empty_returns_recipe_empty ──

def test_publish_empty_recipe_rejected(api):
    """PRD 3.4: "Publishing a recipe ... is permitted only when the recipe is
    currently DRAFT (otherwise ERR_INVALID_STATE) and only when the recipe has at
    least one component (otherwise ERR_RECIPE_EMPTY)."

    Design: Corner/state_machines/recipe_publish_empty_returns_recipe_empty
    """
    member = register_member(business_name="Re")
    mo = make_member_operator_headers(member["id"])
    recipe = validate_success(api.create_recipe(member["id"], {"name": "Empty", "batch_yield_units": 5}, mo), 201)
    res = api.publish_recipe(member["id"], recipe["id"], mo)
    validate_error(res, "ERR_RECIPE_EMPTY")


# ── Corner: state_machines / recipe_retired_is_terminal_no_publish ──

def test_revise_retired_recipe_rejected(api):
    """PRD 3.4: "Retiring a recipe is terminal and moves it from PUBLISHED to
    RETIRED". PRD 3.4: "Revision is permitted only when the recipe is currently
    PUBLISHED (otherwise ERR_INVALID_STATE)". Revising a RETIRED recipe is
    rejected.

    Design: Corner/state_machines/recipe_retired_is_terminal_no_publish
    """
    member = register_member(business_name="Rt")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="RtIng", unit_cost_cents=100)
    recipe = create_published_recipe(member["id"], batch_yield_units=5,
                                     components=[(ing["id"], 1.0)], name="RtR")
    validate_success(api.retire_recipe(member["id"], recipe["id"], mo), 200)
    res = api.revise_recipe(member["id"], recipe["id"], mo)
    validate_error(res, "ERR_INVALID_STATE")


# ── Corner: state_machines / recipe_revise_in_use_returns_recipe_in_use ──

def test_revise_recipe_pinned_by_in_production_batch_rejected(api):
    """PRD 3.4: "Revision is permitted only when the recipe is currently PUBLISHED
    (otherwise ERR_INVALID_STATE) and only when no IN_PRODUCTION batch has pinned
    this recipe's version (otherwise ERR_RECIPE_IN_USE)." The recipe stays
    PUBLISHED.

    Design: Corner/state_machines/recipe_revise_in_use_returns_recipe_in_use
    """
    member = register_member(business_name="Iu")
    mo = make_member_operator_headers(member["id"])
    ing = create_ingredient(name="IuIng", unit_cost_cents=100)
    stock_ingredient(member["id"], ing["id"], 100, 100)
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(ing["id"], 1.0)], name="IuR")
    create_started_batch(member["id"], recipe["id"], planned_yield_units=10)
    res = api.revise_recipe(member["id"], recipe["id"], mo)
    validate_error(res, "ERR_RECIPE_IN_USE")
    still = validate_success(api.get_recipe(recipe["id"], FM), 200)
    assert still["status"] == "PUBLISHED"


# ── Corner: calculations / recipe_allergen_union_computed_on_publish ──

def test_recipe_allergen_union_on_publish(api):
    """PRD 3.4: "The recipe's read-only allergen_tags is set to the union of the
    allergen_tags of every ingredient referenced by its components — the recipe
    inherits every allergen any of its ingredients carries." {MILK} union
    {PEANUT, SOY} = {MILK, PEANUT, SOY}.

    Design: Corner/calculations/recipe_allergen_union_computed_on_publish
    """
    member = register_member(business_name="Al")
    milky = create_ingredient(name="Milky", unit_cost_cents=200, allergen_tags=["MILK"])
    nutsoy = create_ingredient(name="NutSoy", unit_cost_cents=300, allergen_tags=["PEANUT", "SOY"])
    recipe = create_published_recipe(member["id"], batch_yield_units=10,
                                     components=[(milky["id"], 1.0), (nutsoy["id"], 1.0)],
                                     name="AlR")
    tags = recipe["allergen_tags"]
    assert "MILK" in tags
    assert "PEANUT" in tags
    assert "SOY" in tags
