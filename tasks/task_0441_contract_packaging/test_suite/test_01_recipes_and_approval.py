"""Recipe authoring, the approval loop, and BOM-line optimistic concurrency."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_customer, create_component, create_recipe, add_bom_line,
    build_approved_recipe,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import RECEIVER, SCHEDULER, QA


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / recipe_revision_cycle_rejected_back_to_draft
# ---------------------------------------------------------------------------

def test_rejected_recipe_revises_back_to_draft(api):
    """PRD 3.2: "a `Scheduler` may revise it, moving `REJECTED` back to `DRAFT`, which makes the bill-of-materials lines editable again and increments the recipe's `version` by one."

    Design: Difficulty/non_linear_state_machine/recipe_revision_cycle_rejected_back_to_draft
    """
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = create_recipe(customer["id"])
    add_bom_line(recipe["id"], almond["id"], recipe["version"])
    # Adding a BOM line bumps the recipe version (PRD 3.2); re-read for the next add.
    recipe = get_success_data(api.get_recipe(recipe["id"], SCHEDULER))
    add_bom_line(recipe["id"], pouch["id"], recipe["version"], qty_per_unit=1)
    get_success_data(api.submit_recipe(recipe["id"], SCHEDULER))
    get_success_data(api.reject_recipe(recipe["id"], QA))

    revised = validate_success(api.revise_recipe(recipe["id"], SCHEDULER))
    assert revised["status"] == "DRAFT", (
        f"revise must move REJECTED back to DRAFT, got {revised['status']}"
    )


def test_revised_recipe_resubmits_to_pending_approval(api):
    """PRD 3.2: "This closes a cyclic loop — `REJECTED → DRAFT → PENDING_APPROVAL` and then once more to `APPROVED` or `REJECTED` — so a recipe may iterate until it passes."

    Design: Difficulty/non_linear_state_machine/recipe_revision_cycle_rejected_back_to_draft
    """
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = create_recipe(customer["id"])
    add_bom_line(recipe["id"], almond["id"], recipe["version"])
    # Adding a BOM line bumps the recipe version (PRD 3.2); re-read for the next add.
    recipe = get_success_data(api.get_recipe(recipe["id"], SCHEDULER))
    add_bom_line(recipe["id"], pouch["id"], recipe["version"], qty_per_unit=1)
    get_success_data(api.submit_recipe(recipe["id"], SCHEDULER))
    get_success_data(api.reject_recipe(recipe["id"], QA))
    get_success_data(api.revise_recipe(recipe["id"], SCHEDULER))

    resubmitted = validate_success(api.submit_recipe(recipe["id"], SCHEDULER))
    assert resubmitted["status"] == "PENDING_APPROVAL", (
        f"a revised DRAFT recipe must re-submit to PENDING_APPROVAL, "
        f"got {resubmitted['status']}"
    )


# ---------------------------------------------------------------------------
# Queue B — state_machines / approve_recipe_from_draft_invalid_state
# ---------------------------------------------------------------------------

def test_approve_recipe_from_draft_rejected(api):
    """PRD 3.2: "Either decision requires the recipe to be in `PENDING_APPROVAL`, and an attempt from any other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_recipe_from_draft_invalid_state
    """
    customer = create_customer()
    recipe = create_recipe(customer["id"])

    resp = api.approve_recipe(recipe["id"], QA)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue B — state_machines / submit_recipe_without_ingredient_line_invalid_state
# ---------------------------------------------------------------------------

def test_submit_without_ingredient_line_rejected(api):
    """PRD 3.2: "Submission is gated on the bill of materials being complete enough to pack: the recipe must have at least one bill-of-materials line whose component `kind` is `INGREDIENT` and at least one whose `kind` is `PACKAGING`."

    Design: Corner/state_machines/submit_recipe_without_ingredient_line_invalid_state
    """
    customer = create_customer()
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    recipe = create_recipe(customer["id"])
    add_bom_line(recipe["id"], pouch["id"], recipe["version"], qty_per_unit=1)

    resp = api.submit_recipe(recipe["id"], SCHEDULER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_complexity_layers / occ_stale_recipe_version_on_bomline_add
# ---------------------------------------------------------------------------

def test_bomline_add_stale_recipe_version_rejected(api):
    """PRD 2.7: "Adding a bill-of-materials line to a recipe likewise requires `expected_recipe_version`, the client's last observed `version` of the target `Recipe`. If that value does not equal the recipe's current `version ... the add is rejected with `ERR_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_recipe_version_on_bomline_add
    """
    customer = create_customer()
    comp1 = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    comp2 = create_component(customer["id"], "OIL", "Oil", "INGREDIENT")
    recipe = create_recipe(customer["id"])
    stale_version = recipe["version"]
    # First add bumps the recipe version.
    add_bom_line(recipe["id"], comp1["id"], stale_version)

    # Second add reuses the now-stale pre-add version.
    resp = api.add_bom_line(
        recipe["id"],
        {"component_id": comp2["id"], "qty_per_unit": 1,
         "expected_recipe_version": stale_version},
        SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_complexity_layers / occ_correct_version_succeeds_and_bumps
# ---------------------------------------------------------------------------

def test_bomline_add_correct_version_succeeds_and_bumps(api):
    """PRD 3.2: "While the recipe is `DRAFT`, adding a line recomputes the recipe's `allergen_profile` and increments the recipe's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
    """
    customer = create_customer()
    comp1 = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    recipe = create_recipe(customer["id"])
    assert recipe["version"] == 1, "a new recipe begins at version 1"

    validate_success(api.add_bom_line(
        recipe["id"],
        {"component_id": comp1["id"], "qty_per_unit": 2,
         "expected_recipe_version": recipe["version"]},
        SCHEDULER,
    ), expected_status=201)
    # Read the recipe back: its version must have advanced by exactly one.
    after = validate_success(api.get_recipe(recipe["id"], SCHEDULER))
    assert after["version"] == 2, (
        f"adding a bom-line must increment recipe version by one (1 -> 2), "
        f"got {after['version']}"
    )
