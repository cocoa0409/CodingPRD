"""Blend recipes: composition validity, ACTIVE-gated consumers, OCC on
updates, and the retirement cascade into locked batches.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_active_recipe,
    create_batch_payload,
    create_locked_batch_with_allocations,
    create_recipe,
    create_recipe_payload,
    create_released_lot,
    create_supplier,
    get_batch,
    get_lot,
    single_component,
    validate_error,
    validate_paginated,
    validate_success,
)

BM = TEST_USERS["blend_master_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_recipe_composition_invalid_rejected(api):
    """PRD §3.3: "Composition is exact: the component `pct` values plus the
    `flavoring_pct` must sum to exactly 100.00, and empty or malformed
    component arrays are invalid."
    PRD §3.3: "Violations surface as `ERR_RECIPE_COMPOSITION_INVALID`,
    enforced when the recipe is created and checked again at activation."

    Components 60 + 30 with no flavoring sum to 90.0, not 100.00.

    Design: Corner/validations/recipe_composition_invalid_rejected
    """
    res = api.create_recipe(
        create_recipe_payload(
            name="RBad",
            components=[single_component("BLACK", "B", 60.0),
                        single_component("GREEN", "C", 30.0)]), BM)
    validate_error(res, ApiErrorId.ERR_RECIPE_COMPOSITION_INVALID)
    _, meta = validate_paginated(api.list_recipes(BM))
    assert meta["total_count"] == 0, "invalid composition persists no recipe"


def test_batch_create_with_draft_recipe_rejected(api):
    """PRD §3.4: "A `BlendMaster` creates a batch by naming an `ACTIVE`
    recipe's `recipe_id` and a strictly positive `target_weight_kg`
    covering leaf and flavoring combined; referencing a recipe that is not
    `ACTIVE` is rejected with `ERR_RECIPE_NOT_ACTIVE`."
    PRD §3.8: "Activation prices the deal. The referenced recipe must be
    `ACTIVE`, else `ERR_RECIPE_NOT_ACTIVE`"

    Design: Corner/validations/batch_create_with_draft_recipe_rejected
    """
    recipe = create_recipe(name="RDraft")
    assert recipe["status"] == "DRAFT"

    res_batch = api.create_batch(
        create_batch_payload(recipe["id"], target_weight_kg=10.0), BM)
    validate_error(res_batch, ApiErrorId.ERR_RECIPE_NOT_ACTIVE)

    contract = validate_success(
        api.create_contract(
            {"customer_name": "Draft Foods", "recipe_id": recipe["id"],
             "minimum_units_per_run": 100, "contracted_total_units": 1000,
             "base_unit_price_cents": 150}, AM), 201)
    res_activate = api.activate_contract(contract["id"], AM)
    validate_error(res_activate, ApiErrorId.ERR_RECIPE_NOT_ACTIVE)


def test_occ_recipe_put_stale_rejected(api):
    """PRD §2.7: "A request to `PUT /tea-ops/recipes/{id}` must likewise
    include `expected_recipe_version`, and a mismatch with the recipe's
    current `version` is rejected with the same `ERR_STALE_VERSION`
    (HTTP 412), so two edits based on the same observed version cannot
    both succeed."
    PRD §3.3: "the revision request must carry `expected_recipe_version`
    per §2.7, and each accepted revision increments the recipe's `version`
    by one."

    Design: Corner/complexity_layers/occ_recipe_put_stale_rejected
    """
    recipe = create_recipe(name="ROcc")
    assert recipe["status"] == "DRAFT"
    v1 = recipe["version"]

    full_payload = create_recipe_payload(
        name="ROcc-2", certification_target="CONVENTIONAL",
        pack_format="LOOSE_PACK",
        components=[{"leaf_type": "GREEN", "min_grade": "C", "pct": 100.0}])
    full_payload["expected_recipe_version"] = v1
    first = validate_success(api.update_recipe(recipe["id"], full_payload, BM),
                             200)
    assert first["version"] == v1 + 1, "accepted revision increments by one"

    stale_payload = create_recipe_payload(name="ROcc-3")
    stale_payload["expected_recipe_version"] = v1
    res = api.update_recipe(recipe["id"], stale_payload, BM)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    after = validate_success(api.get_recipe(recipe["id"], BM), 200)
    assert after["name"] == "ROcc-2"
    assert after["version"] == v1 + 1


def test_recipe_retire_cascades_to_locked_batch(api):
    """PRD §3.3: "Retirement moves an `ACTIVE` recipe to `RETIRED` and
    cascades: every batch of this recipe still in `DRAFT` or
    `RECIPE_LOCKED` is cancelled, and each such cancellation releases the
    batch's allocations — the `ACTIVE` allocations flip to `RELEASED`, the
    drawn kilograms are credited back to each lot's `remaining_weight_kg`,
    and a `DEPLETED` lot restored above zero returns to `RELEASED`."

    Design: Corner/state_machines/recipe_retire_cascades_to_locked_batch
    """
    supplier = create_supplier(name="Retire Co")
    lot = create_released_lot(supplier["id"], leaf_type="BLACK",
                              weight_kg=30.0)
    recipe = create_active_recipe(
        name="RR", pack_format="TEA_BAG",
        components=[single_component("BLACK", "C", 100.0)])
    batch = create_locked_batch_with_allocations(
        recipe["id"], 20.0, [(lot["id"], 20.0)])
    assert batch["status"] == "RECIPE_LOCKED"
    assert get_lot(lot["id"])["remaining_weight_kg"] == 10.0

    retired = validate_success(api.retire_recipe(recipe["id"], BM), 200)
    assert retired["status"] == "RETIRED"

    batch_after = get_batch(batch["id"])
    assert batch_after["status"] == "CANCELLED"
    lot_after = get_lot(lot["id"])
    assert lot_after["remaining_weight_kg"] == 30.0, (
        "compensation credits the drawn kilograms back")
