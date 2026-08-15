"""Recipe authoring, BOM structural gates, and the scale-up preview (PRD §3.1)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_component,
    assert_recipe,
    create_approved_recipe,
    create_batch,
    create_order,
    create_recipe,
    create_recipe_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    kit_batch,
    pin_clock,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
OPERATOR = TEST_USERS["line_operator_headers"]
QA_TECH = TEST_USERS["qa_technician_headers"]


class TestRecipeCreation:
    def test_recipe_create_applies_defaults(self, api):
        """PRD §3.1: "Every new recipe begins life in `DRAFT` status."
        PRD §2.5: "`id` (string): a unique, server-generated identifier formatted
        as a UUID, with no type prefix." / "`version` (integer): a system-managed
        integer that increments by one with every modification to the resource"

        Design: Corner/entities/recipe_create_applies_defaults
        """
        pin_clock()
        resp = api.create_recipe(
            create_recipe_payload(
                name="R-Def", product_style="SKILLET",
                base_batch_yield_units=500, portion_weight_g=400, shelf_life_days=180,
            ),
            PM,
        )
        data = validate_success(resp, expected_status=201)
        assert_recipe(data)
        assert data["status"] == "DRAFT", f"new recipe must be DRAFT, got {data['status']}"
        assert data["version"] == 1, f"new recipe version must be 1, got {data['version']}"
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert data["updated_at"] == data["created_at"], (
            "updated_at is refreshed on modification; at creation it equals created_at"
        )

    def test_recipe_create_missing_required_returns_400(self, api):
        """PRD §2.4: "Required fields are present, types are correct, enum members
        are valid, and numeric ranges are respected (for example, unit counts must
        be positive and a component's `scale_exponent` must be greater than zero and
        no greater than 1.5); otherwise `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A `PlantManager` authors a recipe by supplying a `name`, a
        `product_style` of `ENTREE`, `BOWL`, or `SKILLET`, a
        `base_batch_yield_units` (the positive integer count of units one base
        batch produces, which serves as the scale-up denominator), a positive
        `portion_weight_g` (the net weight per unit in grams), and a positive
        `shelf_life_days` (the frozen shelf life in days)."

        Design: Corner/entities/recipe_create_missing_required_returns_400
        """
        resp = api.create_recipe(
            {
                "name": "R-Bad",
                "product_style": "ENTREE",
                "base_batch_yield_units": 1000,
                "portion_weight_g": 340,
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestComponentValidation:
    def test_component_create_invalid_enum_returns_400(self, api):
        """PRD §3.1: "a `component_type` of `RAW_INGREDIENT`, `SUB_ASSEMBLY`, or
        `PACKAGING`"
        PRD §2.4: "Required fields are present, types are correct, enum members
        are valid, and numeric ranges are respected (for example, unit counts must
        be positive and a component's `scale_exponent` must be greater than zero
        and no greater than 1.5); otherwise `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/component_create_invalid_enum_returns_400
        """
        recipe = create_recipe(name="R-Enum")
        resp = api.add_component(
            recipe["id"],
            {
                "component_name": "Spice mix",
                "component_type": "SPICE",
                "quantity_per_base_batch": 5,
                "unit_of_measure": "KG",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestRecipeApprovalGates:
    def test_approve_recipe_without_components_rejected(self, api):
        """PRD §3.1: "the recipe must have at least one component line, otherwise
        the approval is rejected with `ERR_RECIPE_NO_COMPONENTS`"

        Design: Corner/validations/approve_recipe_without_components_rejected
        """
        recipe = create_recipe(name="R-Empty")
        resp = api.approve_recipe(recipe["id"], PM)
        validate_error(resp, ApiErrorId.ERR_RECIPE_NO_COMPONENTS, expected_status=409)
        after = validate_success(api.get_recipe(recipe["id"], PM))
        assert after["status"] == "DRAFT", "failed approval must leave the recipe DRAFT"

    def test_approve_recipe_with_component_cycle_rejected(self, api):
        """PRD §3.1: "the component graph formed by `parent_component_id` must be
        acyclic, otherwise the approval is rejected with `ERR_RECIPE_COMPONENT_CYCLE`"
        PRD §3.1: "an existing line may be re-parented by submitting a new
        `parent_component_id`, only while the recipe is `DRAFT`"

        Design: Corner/validations/approve_recipe_with_component_cycle_rejected
        """
        recipe = create_recipe(name="R-Cyc")
        comp_a = add_component(
            recipe["id"], component_name="A", component_type="SUB_ASSEMBLY",
            quantity_per_base_batch=10,
        )
        comp_b = add_component(
            recipe["id"], component_name="B", component_type="SUB_ASSEMBLY",
            quantity_per_base_batch=5, parent_component_id=comp_a["id"],
        )
        resp = api.reparent_component(comp_a["id"], {"parent_component_id": comp_b["id"]}, PM)
        validate_success(resp, expected_status=200)
        resp = api.approve_recipe(recipe["id"], PM)
        validate_error(resp, ApiErrorId.ERR_RECIPE_COMPONENT_CYCLE, expected_status=409)
        after = validate_success(api.get_recipe(recipe["id"], PM))
        assert after["status"] == "DRAFT", "cyclic BOM approval must leave the recipe DRAFT"


class TestRecipeLifecycle:
    def test_recipe_retired_is_terminal_rejected(self, api):
        """PRD §3.1: "Attempting any recipe transition from a state where it is not
        defined — approving a `RETIRED` recipe, for instance — is rejected with
        `ERR_RECIPE_STATE`."
        PRD §3.1: "retirement moves a recipe to the terminal `RETIRED` state —
        reachable from either `DRAFT` or `APPROVED`"

        Design: Corner/state_machines/recipe_retired_is_terminal_rejected
        """
        recipe = create_recipe(name="R-Term")
        retired = validate_success(api.retire_recipe(recipe["id"], PM), expected_status=200)
        assert retired["status"] == "RETIRED"
        resp = api.approve_recipe(recipe["id"], PM)
        validate_error(resp, ApiErrorId.ERR_RECIPE_STATE, expected_status=409)
        after = validate_success(api.get_recipe(recipe["id"], PM))
        assert after["status"] == "RETIRED", "RETIRED is terminal; approve must not move it"

    def test_revise_recipe_with_active_batch_rejected(self, api):
        """PRD §3.1: "Both revision from `APPROVED` and retirement from `APPROVED`
        are blocked while any batch of any order of the recipe occupies a
        non-terminal state, surfacing `ERR_RECIPE_BUSY`"
        PRD §3.3: "A `ProductionPlanner` may cancel a batch outright: from `CREATED`
        the batch simply moves to `CANCELLED`, while cancelling from `ON_HOLD`
        additionally voids every `RESERVED` freezing cycle of the batch"

        Design: Corner/validations/revise_recipe_with_active_batch_rejected
        """
        recipe = create_approved_recipe(name="R-Busy")
        order = create_order(recipe["id"], units_planned=6000)
        batch = create_batch(order["id"], units_planned=6000)
        kit_batch(batch["id"])

        resp = api.revise_recipe(recipe["id"], PM)
        validate_error(resp, ApiErrorId.ERR_RECIPE_BUSY, expected_status=409)

        # Walk the batch to a terminal state via PRD-declared transitions
        # (KITTED -> ON_HOLD -> CANCELLED), then revise must succeed.
        validate_success(
            api.hold_batch(batch["id"], {"reason": "pause for revise"}, QA_TECH),
            expected_status=200,
        )
        cancelled = validate_success(
            api.cancel_batch(batch["id"], PLANNER), expected_status=200
        )
        assert cancelled["status"] == "CANCELLED"
        revised = validate_success(api.revise_recipe(recipe["id"], PM), expected_status=200)
        assert revised["status"] == "DRAFT", (
            "with every batch terminal, revise must return the recipe to DRAFT"
        )


class TestScalePreview:
    def _recipe_with_bom(self, api):
        """DRAFT recipe (base 1000) with a sub-assembly tree and a PACKAGING line."""
        recipe = create_recipe(name="R-Scale", product_style="BOWL")
        add_component(
            recipe["id"], component_name="Sauce base",
            quantity_per_base_batch=50, scale_exponent=0.85,
        )
        sub = add_component(
            recipe["id"], component_name="Grain sub", component_type="SUB_ASSEMBLY",
            quantity_per_base_batch=20, scale_exponent=1.0,
        )
        add_component(
            recipe["id"], component_name="Toasted grain",
            quantity_per_base_batch=5, scale_exponent=0.5,
            parent_component_id=sub["id"],
        )
        add_component(
            recipe["id"], component_name="Tray", component_type="PACKAGING",
            quantity_per_base_batch=200, unit_of_measure="EACH", scale_exponent=0.9,
        )
        return recipe

    def test_scale_preview_factor_passthrough(self, api):
        """PRD §3.1: "The raw scale factor is `target_units` divided by the recipe's
        `base_batch_yield_units`, and the working scale factor clamps that raw value
        to a floor of 0.25 and a ceiling of 8.0."
        PRD §3.1: "answers with the requested `target_units`, the resulting
        `scale_factor`, and one entry per component in `lines`"

        Design: Difficulty/combinatorial_formula/recipe_scale_up_nonlinear_exponents
        """
        recipe = self._recipe_with_bom(api)
        resp = api.scale_preview(recipe["id"], PLANNER, params={"target_units": 2000})
        data = validate_success(resp, expected_status=200)
        assert data["target_units"] == 2000
        assert data["scale_factor"] == pytest.approx(2.0), (
            f"raw factor 2000/1000 lies inside the clamp, got {data['scale_factor']}"
        )
        assert len(data["lines"]) == 4, (
            f"one entry per component in lines; recipe has 4 components, got {len(data['lines'])}"
        )

    def test_scale_preview_factor_clamped_high(self, api):
        """PRD §3.1: "The raw scale factor is `target_units` divided by the recipe's
        `base_batch_yield_units`, and the working scale factor clamps that raw value
        to a floor of 0.25 and a ceiling of 8.0."
        PRD §3.1: "answers with the requested `target_units`, the resulting
        `scale_factor`, and one entry per component in `lines`"

        Design: Difficulty/combinatorial_formula/recipe_scale_up_nonlinear_exponents
        """
        recipe = self._recipe_with_bom(api)
        resp = api.scale_preview(recipe["id"], PLANNER, params={"target_units": 20000})
        data = validate_success(resp, expected_status=200)
        assert data["target_units"] == 20000
        assert data["scale_factor"] == pytest.approx(8.0), (
            f"raw factor 20 must clamp to the 8.0 ceiling, got {data['scale_factor']}"
        )
        assert len(data["lines"]) == 4

    def test_scale_preview_clamps_factor_low(self, api):
        """PRD §3.1: "The raw scale factor is `target_units` divided by the recipe's
        `base_batch_yield_units`, and the working scale factor clamps that raw value
        to a floor of 0.25 and a ceiling of 8.0."
        PRD §3.1: "The preview is available regardless of the recipe's status, so it
        can be used while drafting, after approval, and on retired recipes alike."

        Design: Corner/calculations/scale_preview_clamps_factor_low
        """
        recipe = create_recipe(name="R-Clamp", product_style="BOWL")
        add_component(
            recipe["id"], component_name="Base", quantity_per_base_batch=80,
            scale_exponent=1.0,
        )
        # Preview is available while DRAFT (no approval needed).
        resp = api.scale_preview(recipe["id"], PLANNER, params={"target_units": 100})
        data = validate_success(resp, expected_status=200)
        assert data["target_units"] == 100
        assert data["scale_factor"] == pytest.approx(0.25), (
            f"raw factor 0.1 must clamp up to the 0.25 floor, got {data['scale_factor']}"
        )
        assert len(data["lines"]) == 1, "one entry per component in lines"
