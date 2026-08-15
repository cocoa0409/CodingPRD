"""Blend recipe engineering: components, approval side effects, branching, OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_component,
    approve_recipe,
    assert_blend_component,
    assert_blend_recipe,
    assert_fiber_weight_conservation,
    create_draft_recipe,
    create_fiber_lot,
    get_recipe_version,
    get_success_data,
    is_iso8601_timestamp,
    reject_recipe,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["mill_planner_headers"]


class TestComponentDerivations:
    def test_total_component_weight_recomputed(self, api):
        """PRD §3.1: "Every add re-derives the recipe's `total_component_weight_lbs` as the sum of its component weights and recomputes every component's `proportion_pct` — that component's weight divided by the recipe's total component weight, expressed as a percentage."

        Design: Corner/entities/blend_recipe_total_component_weight_computed
        """
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        recipe = create_draft_recipe(target_yarn_count_ne=20.0)
        add_component(recipe["id"], lot["id"], 75.5)
        add_component(recipe["id"], lot["id"], 24.5)

        fetched = validate_success(api.get_blend_recipe(recipe["id"], PLANNER))
        assert fetched["total_component_weight_lbs"] == pytest.approx(100.0), (
            "total_component_weight_lbs is the sum of component weights (75.5 + 24.5)"
        )

    def test_component_proportion_pct_recomputed(self, api):
        """PRD §3.1: "Every add re-derives the recipe's `total_component_weight_lbs` as the sum of its component weights and recomputes every component's `proportion_pct` — that component's weight divided by the recipe's total component weight, expressed as a percentage."

        Design: Corner/entities/blend_component_proportion_pct_computed
        """
        lot_a = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        lot_b = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=2.0,
                                 fiber_type="POLYESTER")
        recipe = create_draft_recipe(target_yarn_count_ne=20.0)
        comp_a = add_component(recipe["id"], lot_a["id"], 60.0)
        comp_b = add_component(recipe["id"], lot_b["id"], 40.0)
        assert_blend_component(comp_a)
        assert_blend_component(comp_b)

        components = validate_success(
            api.list_blend_components(recipe["id"], PLANNER)
        )
        by_id = {c["id"]: c for c in components}
        assert by_id[comp_a["id"]]["proportion_pct"] == pytest.approx(60.0)
        assert by_id[comp_b["id"]]["proportion_pct"] == pytest.approx(40.0)


class TestApprovalBranch:
    def test_recipe_approve_debits_fiber_lot(self, api):
        """PRD §3.1: "Simultaneously each referenced fiber lot is debited — its `available_weight_lbs` reduced by the component weight it contributes and its `updated_at` refreshed — and any such lot still in `RECEIVED` transitions to `BLENDED`."

        Design: Corner/endpoints/recipe_approve_debits_fiber_lot
        """
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        recipe = create_draft_recipe(target_yarn_count_ne=20.0)
        add_component(recipe["id"], lot["id"], 200.0)
        approve_recipe(recipe["id"])

        after = validate_success(api.get_fiber_lot(lot["id"], PLANNER))
        assert after["available_weight_lbs"] == pytest.approx(300.0)
        assert after["status"] == "BLENDED"

    def test_branch_approve_side_effects(self, api):
        """PRD §3.1: "On approval the recipe's `approved_at` is stamped (it is null until then), its `version` increments, and its `projected_cost_per_lb` is computed with the forward-looking blend cost estimate: the sum, over all components, of each component's weight multiplied by its fiber lot's current `unit_cost_per_lb` at approval time, divided by the recipe's `total_component_weight_lbs`, rounded to 4 decimal places round half up."

        Design: Difficulty/non_linear_state_machine/blend_recipe_branching_approve_or_reject
        """
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        rec_a = create_draft_recipe(recipe_code="BR-APPROVE", target_yarn_count_ne=20.0)
        add_component(rec_a["id"], lot["id"], 100.0)
        rec_b = create_draft_recipe(recipe_code="BR-REJECT", target_yarn_count_ne=20.0)
        add_component(rec_b["id"], lot["id"], 50.0)

        approved = approve_recipe(rec_a["id"])
        reject_recipe(rec_b["id"])

        recipe_a = validate_success(api.get_blend_recipe(rec_a["id"], PLANNER))
        assert recipe_a["status"] == "APPROVED"
        assert is_iso8601_timestamp(recipe_a["approved_at"]), (
            "approved_at is stamped on approval"
        )
        assert recipe_a["projected_cost_per_lb"] == pytest.approx(1.5, abs=1e-4), (
            "forward-looking estimate: (100 * 1.5) / 100 = 1.5000"
        )
        assert_blend_recipe(recipe_a)

        lot_after = validate_success(api.get_fiber_lot(lot["id"], PLANNER))
        assert lot_after["available_weight_lbs"] == pytest.approx(400.0), (
            "Only the approved recipe's 100 lbs is debited; the other recipe's "
            "50 lbs was never committed"
        )
        assert lot_after["status"] == "BLENDED"
        assert_version_fields(approved, rec_a)

    def test_branch_reject_detaches_components(self, api):
        """PRD §3.1: "Rejection is the softer exit: a `DRAFT` recipe rejected by the planner moves to `REJECTED`, all of its components are detached (deleted), no fiber lot weights change, and the recipe's `version` increments."

        Design: Difficulty/non_linear_state_machine/blend_recipe_branching_approve_or_reject
        """
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        rec_a = create_draft_recipe(recipe_code="BR-APPROVE", target_yarn_count_ne=20.0)
        add_component(rec_a["id"], lot["id"], 100.0)
        rec_b = create_draft_recipe(recipe_code="BR-REJECT", target_yarn_count_ne=20.0)
        add_component(rec_b["id"], lot["id"], 50.0)

        approve_recipe(rec_a["id"])
        reject_recipe(rec_b["id"])

        recipe_b = validate_success(api.get_blend_recipe(rec_b["id"], PLANNER))
        assert recipe_b["status"] == "REJECTED"

        components = validate_success(
            api.list_blend_components(rec_b["id"], PLANNER)
        )
        assert components == [], "Rejection detaches (deletes) all components"

        lot_after = validate_success(api.get_fiber_lot(lot["id"], PLANNER))
        assert lot_after["available_weight_lbs"] == pytest.approx(400.0), (
            "The rejected recipe changes no fiber lot weights: only the approved "
            "recipe's 100 lbs is debited (500 - 100)"
        )


class TestInvalidTransitions:
    def test_approve_from_approved_rejected(self, api):
        """PRD §3.1: "Approval proceeds only when the recipe is in `DRAFT`, has at least one component, and every referenced fiber lot is still in `RECEIVED` or `BLENDED` status; a recipe in any other state yields `ERR_INVALID_STATE`."

        Design: Corner/state_machines/blend_recipe_invalid_transition_approve_from_approved
        """
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        recipe = create_draft_recipe(target_yarn_count_ne=20.0)
        add_component(recipe["id"], lot["id"], 100.0)
        approve_recipe(recipe["id"])

        # Carry the CURRENT version so only the state precondition can fail.
        current_version = get_recipe_version(recipe["id"])
        resp = api.approve_blend_recipe(
            recipe["id"], {"expected_recipe_version": current_version}, PLANNER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_recipe_terminal(self, api):
        """PRD §3.1: "Approval proceeds only when the recipe is in `DRAFT`, has at least one component, and every referenced fiber lot is still in `RECEIVED` or `BLENDED` status; a recipe in any other state yields `ERR_INVALID_STATE`."
        PRD §3.1: "Rejection is the softer exit: a `DRAFT` recipe rejected by the planner moves to `REJECTED`, all of its components are detached (deleted), no fiber lot weights change, and the recipe's `version` increments."

        Design: Corner/state_machines/blend_recipe_terminal_lockdown_rejected
        """
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        recipe = create_draft_recipe(target_yarn_count_ne=20.0)
        add_component(recipe["id"], lot["id"], 100.0)
        reject_recipe(recipe["id"])

        current_version = get_recipe_version(recipe["id"])
        resp = api.approve_blend_recipe(
            recipe["id"], {"expected_recipe_version": current_version}, PLANNER
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_recipe_approve(self, api):
        """PRD §2.8: "Approving a blend recipe requires the request to carry `expected_recipe_version` equal to the recipe's current `version`; if the recipe's version has advanced since the client last read it — because components were added or the recipe was otherwise mutated — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from approving a composition it has not observed."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_recipe_approve
        """
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        recipe = create_draft_recipe(target_yarn_count_ne=20.0)
        stale_version = recipe["version"]  # version observed before the mutation
        add_component(recipe["id"], lot["id"], 100.0)  # advances the version

        resp = api.approve_blend_recipe(
            recipe["id"], {"expected_recipe_version": stale_version}, PLANNER
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        after = validate_success(api.get_blend_recipe(recipe["id"], PLANNER))
        assert after["status"] == "DRAFT", "A stale approval must not take effect"


class TestWeightConservation:
    def test_fiber_weight_conservation_partial(self, api):
        """PRD §3.1: "The lot's `available_weight_lbs` is initialized equal to the received weight and is thereafter maintained by blend consumption: it can never fall below zero nor exceed the received weight."
        PRD §3.1: "Simultaneously each referenced fiber lot is debited — its `available_weight_lbs` reduced by the component weight it contributes and its `updated_at` refreshed — and any such lot still in `RECEIVED` transitions to `BLENDED`."

        Design: Difficulty/compensating_invariant/fiber_weight_conservation_across_blend
        """
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        recipe = create_draft_recipe(target_yarn_count_ne=20.0)
        add_component(recipe["id"], lot["id"], 200.0)
        approve_recipe(recipe["id"])

        after = validate_success(api.get_fiber_lot(lot["id"], PLANNER))
        assert after["received_weight_lbs"] == pytest.approx(500.0), (
            "received_weight_lbs is untouched by blend consumption"
        )
        assert after["available_weight_lbs"] == pytest.approx(300.0)
        assert_fiber_weight_conservation(after, consumed_lbs=200.0)

    def test_fiber_weight_conservation_exhaustion(self, api):
        """PRD §3.1: "A lot whose available weight reaches zero automatically transitions from `BLENDED` to `EXHAUSTED`, after which no further components may reference it."

        Design: Difficulty/compensating_invariant/fiber_weight_conservation_across_blend
        """
        lot = create_fiber_lot(received_weight_lbs=500.0, unit_cost_per_lb=1.5)
        recipe = create_draft_recipe(target_yarn_count_ne=20.0)
        add_component(recipe["id"], lot["id"], 500.0)
        approve_recipe(recipe["id"])

        after = validate_success(api.get_fiber_lot(lot["id"], PLANNER))
        assert after["available_weight_lbs"] == pytest.approx(0.0)
        assert after["status"] == "EXHAUSTED", (
            "Full consumption auto-transitions the lot BLENDED -> EXHAUSTED"
        )
        assert_fiber_weight_conservation(after, consumed_lbs=500.0)


def assert_version_fields(approved_recipe, created_recipe):
    """The approve response reflects the version increment from approval."""
    assert approved_recipe["version"] > created_recipe["version"]
