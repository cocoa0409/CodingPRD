"""Cocktail recipes, pour-cost rounding, the publish/revise cycle, menu items,
menu engineering, and sales recording.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_product, create_draft_recipe_with_lines, create_published_recipe,
    create_menu_item, record_sales, get_product,
    BAR_MANAGER, INVENTORY_MANAGER,
)


def _three_margarita_products(suffix):
    teq = create_product(sku=f"TEQ-{suffix}", name="Tequila", container_volume_ml=750, unit_cost_cents=2495)
    coin = create_product(sku=f"COIN-{suffix}", name="Cointreau", container_volume_ml=700, unit_cost_cents=3200)
    lime = create_product(sku=f"LIME-{suffix}", name="Lime Juice", container_volume_ml=1000, unit_cost_cents=600)
    return teq, coin, lime


def test_recipe_cost_rounds_per_line_then_sums(api):
    """PRD §3.3: "The cost of a single pour line, `line_cost_cents`, is the ingredient
    product's `unit_cost_cents` multiplied by the line's `pour_ml`, divided by that
    product's `container_volume_ml`, with the result rounded half-up to a whole cent.
    A recipe's `recipe_cost_cents` is then the sum of the `line_cost_cents` of every one
    of its lines, taken across all lines regardless of any filter, with the lines
    considered in order of their creation time."

    Design: Difficulty/dual_variant_calc/recipe_cost_round_per_line_vs_sum_then_round
    """
    teq, coin, lime = _three_margarita_products("A")
    rec = create_draft_recipe_with_lines("Margarita", [
        {"product_id": teq["id"], "pour_ml": 50},
        {"product_id": coin["id"], "pour_ml": 25},
        {"product_id": lime["id"], "pour_ml": 25},
    ])
    data = validate_success(api.publish_recipe(rec["id"], BAR_MANAGER))
    assert data["recipe_cost_cents"] == 295, f"round-per-line sum, got {data['recipe_cost_cents']}"

    lines = validate_success(api.list_recipe_lines(rec["id"], BAR_MANAGER))
    by_product = {ln["product_id"]: ln["line_cost_cents"] for ln in lines}
    assert by_product[teq["id"]] == 166
    assert by_product[coin["id"]] == 114
    assert by_product[lime["id"]] == 15


def test_recipe_cost_rounding_order_excludes_sum_then_round(api):
    """PRD §3.3: "The rounding order here is deliberate and contractual: each line is
    rounded to a whole cent first, and only then are the rounded line costs summed. The
    naive alternative — summing the raw fractional line costs and rounding once at the
    end — is explicitly not used, because the two approaches can differ by a cent."

    Design: Difficulty/combinatorial_formula/recipe_cost_rounding_order_mode_b
    """
    teq, coin, lime = _three_margarita_products("B")
    rec = create_draft_recipe_with_lines("Margarita B", [
        {"product_id": teq["id"], "pour_ml": 50},
        {"product_id": coin["id"], "pour_ml": 25},
        {"product_id": lime["id"], "pour_ml": 25},
    ])
    data = validate_success(api.publish_recipe(rec["id"], BAR_MANAGER))
    assert data["recipe_cost_cents"] == 295, "round-per-line authoritative"
    assert data["recipe_cost_cents"] != 296, "sum-then-round value (296) is rejected"


def test_pour_cost_pct_computed_on_menu_item(api):
    """PRD §3.4: "The item's pour-cost percentage, `pour_cost_pct`, is the referencing
    recipe's `recipe_cost_cents` divided by the item's `menu_price_cents`, multiplied by
    one hundred and carried to two decimal places."

    Design: Corner/calculations/pour_cost_pct_computed_on_menu_item
    """
    teq, coin, lime = _three_margarita_products("PC")
    rec = create_published_recipe("Marg PC", [
        {"product_id": teq["id"], "pour_ml": 50},
        {"product_id": coin["id"], "pour_ml": 25},
        {"product_id": lime["id"], "pour_ml": 25},
    ])
    assert rec["recipe_cost_cents"] == 295
    mi = create_menu_item(rec["id"], menu_price_cents=1300)
    assert mi["pour_cost_pct"] == 22.69, f"295/1300*100 = 22.69, got {mi['pour_cost_pct']}"


def test_publish_then_revise_returns_to_draft(api):
    """PRD §3.3: "A published recipe can be sent back for editing by revising it, which
    is allowed only while it is `PUBLISHED` and no active menu item references it,
    returning it to `DRAFT`."

    Design: Difficulty/non_linear_state_machine/recipe_publish_revise_cycle
    """
    # NOTE: the exact `version` integer after create -> add-line -> publish -> revise
    # is NOT uniquely derivable from the PRD. PRD §2.4 declares derived-field
    # recomputes (recipe_cost_cents on line-add and on publish) to be version-bumping
    # mutations, but the PRD never pins how many such bumps occur in each transition
    # (e.g. whether publish's cost-recompute and status-change collapse to one bump or
    # two). A faithful PRD-only implementer could land on 3, 4, or 5. Only the
    # state transition (PUBLISHED -> DRAFT) is uniquely determined, so we assert that.
    rum = create_product(sku="RUM-R", name="Rum", container_volume_ml=750, unit_cost_cents=1800)
    rec = create_published_recipe("Daiquiri", [{"product_id": rum["id"], "pour_ml": 60}])
    assert rec["status"] == "PUBLISHED"
    data = validate_success(api.revise_recipe(rec["id"], BAR_MANAGER))
    assert data["status"] == "DRAFT"


def test_revise_recipe_blocked_by_active_menu_item(api):
    """PRD §3.3: "A published recipe can be sent back for editing by revising it, which
    is allowed only while it is `PUBLISHED` and no active menu item references it,
    returning it to `DRAFT`."
    PRD §3.3: "Attempting any of these transitions from a state that does not allow it
    is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/revise_recipe_blocked_by_active_menu_item
    """
    p = create_product(sku="P-RV", name="A", container_volume_ml=750, unit_cost_cents=1000)
    rec = create_published_recipe("Sour", [{"product_id": p["id"], "pour_ml": 45}])
    create_menu_item(rec["id"], menu_price_cents=1200)
    validate_error(api.revise_recipe(rec["id"], BAR_MANAGER), ApiErrorId.ERR_INVALID_STATE)


def test_menu_item_requires_published_recipe(api):
    """PRD §3.4: "A menu item may only reference a recipe whose `status` is `PUBLISHED`;
    an attempt to list a recipe that is not published is rejected with
    `ERR_RECIPE_NOT_PUBLISHED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/menuitem_requires_recipe_published
    """
    gin = create_product(sku="GIN-X7", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    rec = create_draft_recipe_with_lines("Negroni", [{"product_id": gin["id"], "pour_ml": 30}])
    # Recipe is still DRAFT.
    validate_error(
        api.create_menu_item({"recipe_id": rec["id"], "menu_price_cents": 1400}, BAR_MANAGER),
        ApiErrorId.ERR_RECIPE_NOT_PUBLISHED)


def test_menu_item_on_nonexistent_recipe_returns_not_found(api):
    """PRD §2.5: "The first reference that does not resolve to an existing resource
    causes the request to fail with `ERR_NOT_FOUND` (HTTP 404) before any business rule
    runs."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_recipe_not_published
    """
    validate_error(
        api.create_menu_item(
            {"recipe_id": "00000000-0000-4000-8000-000000000000", "menu_price_cents": 1200},
            BAR_MANAGER),
        ApiErrorId.ERR_NOT_FOUND)


def test_record_sales_accumulates_units_sold(api):
    """PRD §3.4: "recording sales adds the `quantity` to the item's cumulative
    `units_sold`, which is what drives both theoretical depletion and menu engineering."

    Design: Corner/endpoints/record_sales_accumulates_units_sold
    """
    rum = create_product(sku="RUM-RS", name="Rum", container_volume_ml=750, unit_cost_cents=1800)
    rec = create_published_recipe("Daiq RS", [{"product_id": rum["id"], "pour_ml": 60}])
    mi = create_menu_item(rec["id"], menu_price_cents=900)
    record_sales(mi["id"], 30, "2026-03-05T00:00:00Z")
    data = validate_success(api.record_sales(
        mi["id"], {"quantity": 10, "sold_at": "2026-03-06T00:00:00Z"}, BAR_MANAGER))
    assert data["units_sold"] == 40, f"30 + 10 accumulates, got {data['units_sold']}"


def test_menu_engineering_classifies_star_and_dog(api):
    """PRD §3.4: "An item that is both high-popularity and high-margin is classified
    `STAR`; one that is high-popularity but not high-margin is `PLOWHORSE`; one that is
    high-margin but not high-popularity is `PUZZLE`; and one that is neither is `DOG`."

    Design: Corner/calculations/menu_engineering_classifies_star_and_dog
    """
    teq = create_product(sku="TEQ-ME", name="Tequila", container_volume_ml=750, unit_cost_cents=2495)
    coin = create_product(sku="COIN-ME", name="Cointreau", container_volume_ml=700, unit_cost_cents=3200)
    lime = create_product(sku="LIME-ME", name="Lime", container_volume_ml=1000, unit_cost_cents=600)
    rum = create_product(sku="RUM-ME", name="Rum", container_volume_ml=750, unit_cost_cents=1800)
    recA = create_published_recipe("Marg ME", [
        {"product_id": teq["id"], "pour_ml": 50},
        {"product_id": coin["id"], "pour_ml": 25},
        {"product_id": lime["id"], "pour_ml": 25},
    ])  # recipe_cost 295
    recB = create_published_recipe("Daiq ME", [{"product_id": rum["id"], "pour_ml": 60}])  # cost 144
    miA = create_menu_item(recA["id"], menu_price_cents=1300)  # margin 1005
    miB = create_menu_item(recB["id"], menu_price_cents=800)   # margin 656
    record_sales(miA["id"], 80, "2026-03-05T00:00:00Z")
    record_sales(miB["id"], 20, "2026-03-05T00:00:00Z")

    report = validate_success(api.menu_engineering(BAR_MANAGER))
    by_id = {m["id"]: m["menu_class"] for m in report}
    assert by_id[miA["id"]] == "STAR"
    assert by_id[miB["id"]] == "DOG"


def test_delist_menu_item_transitions_to_delisted(api):
    """PRD §3.4: "Delisting a menu item moves its `status` to `DELISTED`, bumps its
    `version`, and removes it from the universe of items eligible for sales recording and
    for the menu-engineering and depletion calculations."

    Design: Corner/state_machines/delist_menu_item_then_excluded_from_engineering
    """
    rum = create_product(sku="RUM-DL", name="Rum", container_volume_ml=750, unit_cost_cents=1800)
    recA = create_published_recipe("Daiq DL", [{"product_id": rum["id"], "pour_ml": 60}])
    recB = create_published_recipe("Daiq DL2", [{"product_id": rum["id"], "pour_ml": 60}])
    miA = create_menu_item(recA["id"], menu_price_cents=1300)
    miB = create_menu_item(recB["id"], menu_price_cents=800)
    record_sales(miA["id"], 50, "2026-03-05T00:00:00Z")
    record_sales(miB["id"], 50, "2026-03-05T00:00:00Z")

    # NOTE: the exact `version` integer after create -> record-sales -> delist is NOT
    # uniquely derivable from the PRD. PRD §2.4 declares the pour_cost_pct recompute on
    # create and the units_sold update on record-sales to be version-bumping mutations,
    # but the PRD never pins the precise count (e.g. whether create's pour_cost_pct init
    # is a separate mutation). A faithful PRD-only implementer could land on 2, 3, or 4.
    # Only the state transition (ACTIVE -> DELISTED) is uniquely determined.
    data = validate_success(api.delist_menu_item(miB["id"], BAR_MANAGER))
    assert data["status"] == "DELISTED"


def test_recipe_cost_equals_sum_of_rounded_line_costs(api):
    """PRD §3.3: "A recipe's `recipe_cost_cents` is then the sum of the `line_cost_cents`
    of every one of its lines, taken across all lines regardless of any filter, with the
    lines considered in order of their creation time."

    Design: Difficulty/dual_variant_calc/recipe_cost_round_per_line_vs_sum_then_round
    """
    teq, coin, lime = _three_margarita_products("A2")
    rec = create_draft_recipe_with_lines("Margarita A2", [
        {"product_id": teq["id"], "pour_ml": 50},
        {"product_id": coin["id"], "pour_ml": 25},
        {"product_id": lime["id"], "pour_ml": 25},
    ])
    published = validate_success(api.publish_recipe(rec["id"], BAR_MANAGER))
    lines = validate_success(api.list_recipe_lines(rec["id"], BAR_MANAGER))
    summed_rounded = sum(ln["line_cost_cents"] for ln in lines)
    assert published["recipe_cost_cents"] == summed_rounded, \
        "recipe cost is the exact sum of already-rounded per-line costs"
    assert summed_rounded == 295


def test_single_line_cost_rounds_half_up_to_whole_cent(api):
    """PRD §3.3: "The cost of a single pour line, `line_cost_cents`, is the ingredient
    product's `unit_cost_cents` multiplied by the line's `pour_ml`, divided by that
    product's `container_volume_ml`, with the result rounded half-up to a whole cent."

    Design: Difficulty/combinatorial_formula/recipe_cost_rounding_order_mode_b
    """
    # 2000 * 50 / 750 = 133.333... -> 133 (half-up rounding to a whole cent).
    p = create_product(sku="GIN-RND", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    rec = create_published_recipe("One Pour", [{"product_id": p["id"], "pour_ml": 50}])
    assert rec["recipe_cost_cents"] == 133, f"single line rounds to 133, got {rec['recipe_cost_cents']}"
    lines = validate_success(api.list_recipe_lines(rec["id"], BAR_MANAGER))
    assert lines[0]["line_cost_cents"] == 133


def test_revise_returns_published_recipe_to_editable_draft(api):
    """PRD §3.3: "A published recipe can be sent back for editing by revising it, which is
    allowed only while it is `PUBLISHED` and no active menu item references it, returning
    it to `DRAFT`."

    Design: Difficulty/non_linear_state_machine/recipe_publish_revise_cycle
    """
    p = create_product(sku="RUM-R2", name="Rum", container_volume_ml=750, unit_cost_cents=1800)
    rec = create_published_recipe("Daiquiri 2", [{"product_id": p["id"], "pour_ml": 60}])
    revised = validate_success(api.revise_recipe(rec["id"], BAR_MANAGER))
    assert revised["status"] == "DRAFT"
    # Back in DRAFT, the recipe accepts a new line again (only DRAFT recipes are editable).
    line = validate_success(api.add_recipe_line(
        rec["id"], {"product_id": p["id"], "pour_ml": 15}, BAR_MANAGER), expected_status=201)
    assert line["recipe_id"] == rec["id"]


def test_menu_item_on_published_recipe_succeeds(api):
    """PRD §3.4: "A `BarManager` lists a recipe for sale by creating a `MenuItem`,
    supplying the `recipe_id` and a `menu_price_cents` that must be greater than zero. A
    menu item may only reference a recipe whose `status` is `PUBLISHED`."

    Design: Difficulty/cross_entity_state_dependency/menuitem_requires_recipe_published
    """
    gin = create_product(sku="GIN-X7B", name="Gin", container_volume_ml=750, unit_cost_cents=2000)
    rec = create_published_recipe("Negroni Pub", [{"product_id": gin["id"], "pour_ml": 30}])
    data = validate_success(api.create_menu_item(
        {"recipe_id": rec["id"], "menu_price_cents": 1400}, BAR_MANAGER), expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["recipe_id"] == rec["id"]


def test_menu_item_nonexistent_recipe_not_found_even_with_bad_price(api):
    """PRD §2.5: "Authentication is checked before authorization; authorization before
    resource existence; existence before state legality; state legality before
    optimistic-concurrency version checks; and only then are the domain-specific business
    rules evaluated."

    Design: Difficulty/priority_pair_validation_conflict/not_found_beats_recipe_not_published
    """
    # The recipe id does not resolve; existence (404) precedes the publish-status business
    # rule, so ERR_NOT_FOUND surfaces regardless of other line content.
    validate_error(
        api.create_menu_item(
            {"recipe_id": "11111111-1111-4111-8111-111111111111", "menu_price_cents": 999},
            BAR_MANAGER),
        ApiErrorId.ERR_NOT_FOUND)
