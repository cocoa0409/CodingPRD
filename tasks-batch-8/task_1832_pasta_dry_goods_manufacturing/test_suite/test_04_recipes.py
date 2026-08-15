"""Recipes: conditional private-label fields, ingredient junction rows,
formula gate, retire/amend transitions, and list pagination."""
from test_helpers import (
    ApiErrorId,
    approve_recipe,
    assert_recipe,
    create_recipe_draft,
    create_recipe_payload,
    get_lot,
    set_clock,
    setup_scheduled_run,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
QAM = TEST_USERS["qa_manager_headers"]
OP = TEST_USERS["production_operator_headers"]


def test_recipe_private_label_conditional_field_rules(api):
    """PRD: "a `customer_name` that is required exactly when the brand type is
    `PRIVATE_LABEL` and forbidden otherwise"
    PRD: "for private-label recipes a `min_remaining_shelf_life_pct` between 0
    and 1 expressing the minimum fraction of shelf life that must remain at
    release — the inclusive boundary passes"

    Design: Corner/entities/recipe_private_label_conditional_field_rules
    """
    resp1 = api.create_recipe(create_recipe_payload(
        recipe_name="PL Missing Customer", brand_type="PRIVATE_LABEL",
        min_remaining_shelf_life_pct=0.75), PM)
    validate_error(resp1, ApiErrorId.ERR_INVALID_REQUEST)

    resp2 = api.create_recipe(create_recipe_payload(
        recipe_name="PL Missing Shelf Min", brand_type="PRIVATE_LABEL",
        customer_name="Acme Retail"), PM)
    validate_error(resp2, ApiErrorId.ERR_INVALID_REQUEST)

    resp3 = api.create_recipe(create_recipe_payload(
        recipe_name="Branded With Customer", brand_type="BRANDED",
        customer_name="Acme Retail"), PM)
    validate_error(resp3, ApiErrorId.ERR_INVALID_REQUEST)

    ok = validate_success(api.create_recipe(create_recipe_payload(
        recipe_name="PL Valid", brand_type="PRIVATE_LABEL",
        customer_name="Acme Retail", min_remaining_shelf_life_pct=0.75), PM), 201)
    assert_recipe(ok)
    assert ok["status"] == "DRAFT"
    assert ok["customer_name"] == "Acme Retail"
    assert ok["min_remaining_shelf_life_pct"] == 0.75


def test_recipe_ingredients_created_as_junction_rows(api):
    """PRD: "The creation payload also embeds an `ingredients` array, each row
    of which becomes an immutable `RecipeIngredient` carrying its
    `ingredient_type`, its formula `percentage`, and optionally a
    `min_protein_pct`"

    Design: Corner/entities/recipe_ingredients_created_as_junction_rows
    """
    recipe = create_recipe_draft(
        recipe_name="Blend 80/20", shape_family="SHORT_CUT",
        ingredients=[
            {"ingredient_type": "SEMOLINA", "percentage": 80.0, "min_protein_pct": 12.5},
            {"ingredient_type": "DURUM_SEMOLINA", "percentage": 20.0},
        ],
    )
    rows = validate_success(api.list_recipe_ingredients(recipe["id"], PM))
    assert len(rows) == 2, f"expected 2 junction rows, got {len(rows)}"
    by_type = {r["ingredient_type"]: r for r in rows}
    semolina = by_type["SEMOLINA"]
    durum = by_type["DURUM_SEMOLINA"]
    assert semolina["percentage"] == 80.0
    assert semolina["min_protein_pct"] == 12.5
    assert durum["percentage"] == 20.0
    assert durum.get("min_protein_pct") is None
    for row in rows:
        assert row["recipe_id"] == recipe["id"]


def test_recipe_formula_sum_gate_at_approve(api):
    """PRD: "the recipe carries at least one ingredient row, and the rows'
    `percentage` values sum to exactly 100.00 (`ERR_RECIPE_FORMULA_INVALID`)"

    Design: Corner/validations/recipe_formula_sum_gate_at_approve
    """
    bad = create_recipe_draft(recipe_name="Bad Sum", ingredients=[
        {"ingredient_type": "SEMOLINA", "percentage": 60.0},
        {"ingredient_type": "DURUM_SEMOLINA", "percentage": 30.0},
    ])
    good = create_recipe_draft(recipe_name="Good Sum", ingredients=[
        {"ingredient_type": "SEMOLINA", "percentage": 60.0},
        {"ingredient_type": "DURUM_SEMOLINA", "percentage": 40.0},
    ])

    resp = api.approve_recipe(bad["id"], QAM)
    validate_error(resp, ApiErrorId.ERR_RECIPE_FORMULA_INVALID)
    still = validate_success(api.get_recipe(bad["id"], PM))
    assert still["status"] == "DRAFT"

    approved = approve_recipe(good["id"])
    assert approved["status"] == "APPROVED"


def test_recipe_retire_from_draft_rejected(api):
    """PRD: "A `PlantManager` may also retire an approved recipe, moving it to
    `RETIRED`"
    PRD: "then transition legality on the target resource as
    `ERR_INVALID_STATE`"

    Design: Corner/state_machines/recipe_retire_from_draft_rejected
    """
    recipe = create_recipe_draft(recipe_name="Draft Only")
    resp = api.retire_recipe(recipe["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_recipe_amend_stales_pinned_run(api):
    """PRD: "The create snapshots `pinned_recipe_version` from the recipe's
    current `version`"
    PRD: "the `target_moisture_pct` is replaced and the recipe's `version`
    increments — and because every run pins the recipe version it was created
    against (see §3.4), existing runs now hold a stale pin and will fail at
    mixing with `ERR_RECIPE_REVISION_STALE`"

    Design: Corner/validations/recipe_amend_stales_pinned_run
    """
    sc = setup_scheduled_run(contract_code="C-AMD", planned_input_kg=100.0)
    assert sc["run"]["pinned_recipe_version"] == 2, "create 1, approve bumps to 2"

    amended = validate_success(
        api.amend_recipe(sc["recipe"]["id"], {"target_moisture_pct": 12.0}, PM))
    assert amended["version"] == 3

    set_clock("2026-08-10T00:00:00Z")
    resp = api.advance_run(sc["run"]["id"], {}, OP)
    validate_error(resp, ApiErrorId.ERR_RECIPE_REVISION_STALE)

    run_after = validate_success(api.get_production_run(sc["run"]["id"], OP))
    assert run_after["production_status"] == "SCHEDULED"
    lot = get_lot(sc["lot"]["id"])
    assert lot["remaining_weight_kg"] == 1000.0, "no consumption on the rejected hop"


def test_recipes_listing_pagination_envelope(api):
    """PRD: "List endpoints accept optional `limit` and `offset` query
    parameters."
    PRD: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`"

    Design: Corner/entities/recipes_listing_pagination_envelope
    """
    for name in ("PG A", "PG B", "PG C"):
        create_recipe_draft(recipe_name=name)

    page1, meta1 = validate_paginated(api.list_recipes(PM, params={"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api.list_recipes(PM, params={"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
