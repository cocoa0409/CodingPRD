"""Recipe authoring, approval, and hazard profiling (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    assert_recipe,
    create_approved_recipe,
    create_customer,
    create_recipe,
    receive_lot,
    validate_error,
    validate_success,
)


class TestRecipeApproval:
    def test_double_approve_rejected(self, api, quality_manager_headers):
        """PRD §3.3: "Approval moves the recipe from `DRAFT` to `APPROVED`" —
        an already-APPROVED recipe is no longer in the required source state,
        and PRD §2.9 maps that to `ERR_INVALID_STATE` ("source-state validity
        for the requested transition (`ERR_INVALID_STATE`)").

        Design: Corner/state_machines/recipe_approve_from_approved_returns_invalid_state
        """
        customer = create_customer("R-Corp")
        recipe = create_approved_recipe(
            customer["id"], name="R1",
            components=[{"material_code": "A", "mass_fraction_pct": 100.0,
                         "charge_order": 1}])
        assert recipe["status"] == "APPROVED"

        resp = api.approve_recipe(recipe["id"], quality_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_fraction_sum_invalid_rejected_at_create(
            self, api, quality_manager_headers):
        """PRD §3.3: "The mass fractions across the list must sum to exactly
        100.000, within a tolerance of 0.000001" and "Composition failures at
        creation are rejected with `ERR_RECIPE_FRACTION_SUM_INVALID`
        (HTTP 422)."

        Design: Corner/state_machines/recipe_fraction_sum_invalid_rejected_at_create
        """
        customer = create_customer("Bad Recipe Inc")
        resp = api.create_recipe(
            {"name": "Bad", "revision": 1, "customer_id": customer["id"],
             "target_density_kg_per_l": 1.0, "theoretical_yield_pct": 100,
             "components": [{"material_code": "A", "mass_fraction_pct": 99.999,
                             "charge_order": 1}]},
            quality_manager_headers)
        validate_error(resp, ApiErrorId.ERR_RECIPE_FRACTION_SUM_INVALID)


class TestHazardProfiling:
    def test_highest_component_ghs_uses_severity_order(self, api,
                                                       quality_manager_headers):
        """PRD §3.3: "each component's material code is looked up against the
        customer's raw-material lots — every lot of a given `material_code`
        for a customer shares the same `ghS_class` — and the class sitting
        highest in the severity order of §2.6 wins". PRD §2.6: "from most to
        least severe: `FLAMMABLE`, then `OXIDIZER`, then `TOXIN`, then
        `ACID`, then `BASE`, then `NON_HAZ`."

        Design: Corner/calculations/highest_component_ghs_uses_severity_order
        """
        customer = create_customer("Haz Co")
        receive_lot(customer["id"], material_code="F", ghs_class="FLAMMABLE",
                    quantity_kg_received=100)
        receive_lot(customer["id"], material_code="A", ghs_class="ACID",
                    quantity_kg_received=100)
        receive_lot(customer["id"], material_code="N", ghs_class="NON_HAZ",
                    quantity_kg_received=100)

        resp = api.create_recipe(
            {"name": "Haz Mix", "revision": 1, "customer_id": customer["id"],
             "target_density_kg_per_l": 1.0, "theoretical_yield_pct": 100,
             "components": [
                 {"material_code": "N", "mass_fraction_pct": 50.0,
                  "charge_order": 1},
                 {"material_code": "A", "mass_fraction_pct": 30.0,
                  "charge_order": 2},
                 {"material_code": "F", "mass_fraction_pct": 20.0,
                  "charge_order": 3},
             ]},
            quality_manager_headers)
        recipe = validate_success(resp, 201)
        assert_recipe(recipe)
        assert recipe["highest_component_ghs"] == "FLAMMABLE", (
            f"FLAMMABLE (severity 5) must beat ACID and NON_HAZ, got "
            f"{recipe['highest_component_ghs']}")
