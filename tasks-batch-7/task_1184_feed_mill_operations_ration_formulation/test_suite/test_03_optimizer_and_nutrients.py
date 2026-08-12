"""Least-cost ration optimization: greedy clamp, tie-breaks, feasibility, and
nutrient-constraint boundaries (PRD §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_ingredient, add_price_tick, make_formula, optimize_formula,
    assert_formula,
)

MM = TEST_USERS["mill_manager_headers"]
NUT = TEST_USERS["nutritionist_headers"]


def _three_way_catalog():
    """CORN 30000 / WHEAT 33000 / SBM 52000, all ACTIVE and priced."""
    corn = make_ingredient("CORN")
    wheat = make_ingredient("WHEAT")
    sbm = make_ingredient("SBM")
    add_price_tick(corn["id"], 30000)
    add_price_tick(wheat["id"], 33000)
    add_price_tick(sbm["id"], 52000)
    return corn, wheat, sbm


class TestOptimizerGreedyClamp:
    def test_optimizer_greedy_clamp_lines_and_protein(self, api):
        """PRD §3.4: "Candidates are ranked cheapest first; ties on price break toward the higher `crude_protein_pct`, and further ties break toward the earlier `created_at`."
        PRD §3.4: "Starting from a remaining share of one hundred percent, each candidate in rank order contributes the smaller of seventy percent and the remaining share; a line is appended only when that contribution is positive, and the walk stops the moment the remaining share reaches zero."

        Design: Difficulty/combinatorial_formula/optimizer_greedy_clamped_allocation
        """
        corn, wheat, sbm = _three_way_catalog()
        formula = make_formula("F-3WAY", min_protein_pct=5.0,
                               max_fiber_pct=20.0, min_energy_kcal_kg=1000)
        solved = optimize_formula(formula)
        assert_formula(solved)

        # Cheapest-first: corn takes the 70 clamp; wheat collides with the
        # moving remainder and is clamped to 30; SBM is squeezed out entirely.
        assert [(l["ingredient_id"], l["inclusion_pct"]) for l in solved["lines"]] == [
            (corn["id"], 70), (wheat["id"], 30)]
        # 0.7 * 9.0 + 0.3 * 12.0 = 9.9
        assert solved["total_protein_pct"] == pytest.approx(9.9, abs=0.001)

    def test_optimizer_greedy_clamp_cost_and_constraints(self, api):
        """PRD §3.4: "`provisional_cost_cents_per_ton` is the sum of the per-line projections, rounded half-up once at the very end to integer cents."
        PRD §3.4: "The formula `meets_constraints` exactly when `total_protein_pct` is at least `min_protein_pct`, `total_fiber_pct` is at most `max_fiber_pct`, and `total_energy_kcal_kg` is at least `min_energy_kcal_kg`."

        Design: Difficulty/combinatorial_formula/optimizer_greedy_clamped_allocation
        """
        corn, wheat, sbm = _three_way_catalog()
        formula = make_formula("F-3WAY", min_protein_pct=5.0,
                               max_fiber_pct=20.0, min_energy_kcal_kg=1000)
        solved = optimize_formula(formula)

        # 0.7 * 30000 + 0.3 * 33000 = 30900
        assert solved["provisional_cost_cents_per_ton"] == 30900
        assert solved["meets_constraints"] is True


class TestOptimizerTieBreaksAndFeasibility:
    def test_optimizer_price_tie_breaks_by_protein_desc(self, api):
        """PRD §3.4: "Candidates are ranked cheapest first; ties on price break toward the higher `crude_protein_pct`, and further ties break toward the earlier `created_at`."

        Design: Corner/calculations/optimizer_price_tie_breaks_by_protein_desc
        """
        corn = make_ingredient("CORN")
        wheat = make_ingredient("WHEAT")
        add_price_tick(corn["id"], 30000)
        add_price_tick(wheat["id"], 30000)
        formula = make_formula("F-TIE", min_protein_pct=5.0,
                               max_fiber_pct=20.0, min_energy_kcal_kg=1000)
        solved = optimize_formula(formula)

        # Equal prices: wheat (protein 12.0) outranks corn (protein 9.0).
        assert [(l["ingredient_id"], l["inclusion_pct"]) for l in solved["lines"]] == [
            (wheat["id"], 70), (corn["id"], 30)]
        assert solved["provisional_cost_cents_per_ton"] == 30000

    def test_optimizer_infeasible_with_single_candidate_rejected(self, api):
        """PRD §3.4: "If the candidate set is empty, or if seventy percent per candidate multiplied by the number of candidates falls short of one hundred percent, the run is rejected with `ERR_FORMULA_NOT_FEASIBLE`."

        Design: Corner/calculations/optimizer_infeasible_with_single_candidate_rejected
        """
        corn = make_ingredient("CORN")
        add_price_tick(corn["id"], 30000)
        formula = make_formula("F-ONE", min_protein_pct=5.0,
                               max_fiber_pct=20.0, min_energy_kcal_kg=1000)

        # 70 * 1 candidate = 70 < 100: the ration cannot reach 100 percent.
        resp = api.optimize_formula(
            formula["id"], {"expected_formula_version": formula["version"]}, NUT)
        validate_error(resp, ApiErrorId.ERR_FORMULA_NOT_FEASIBLE)

        after = validate_success(api.get_formula(formula["id"], NUT), 200)
        assert after["lines"] == []
        assert after["status"] == "DRAFT"


class TestNutrientFloorBoundary:
    def _catalog_19_5(self):
        """Catalogue whose optimal ration (corn70/SBM30) totals protein 19.50."""
        corn = make_ingredient("CORN")
        sbm = make_ingredient("SBM")
        add_price_tick(corn["id"], 30000)
        add_price_tick(sbm["id"], 52000)

    def test_nutrient_protein_exactly_at_floor_meets_and_activates(self, api):
        """PRD §3.4: "The formula `meets_constraints` exactly when `total_protein_pct` is at least `min_protein_pct`, `total_fiber_pct` is at most `max_fiber_pct`, and `total_energy_kcal_kg` is at least `min_energy_kcal_kg`."

        Design: Difficulty/boundary_precision_check/nutrient_protein_exactly_at_min_meets
        """
        self._catalog_19_5()
        formula = make_formula("F-EXACT", min_protein_pct=19.5,
                               max_fiber_pct=5.0, min_energy_kcal_kg=3000)
        solved = optimize_formula(formula)
        # corn70/SBM30: 0.7 * 9.0 + 0.3 * 44.0 = 19.5 — the floor comparison
        # is inclusive, so exactly-at-floor meets.
        assert solved["total_protein_pct"] == pytest.approx(19.5, abs=0.001)
        assert solved["meets_constraints"] is True

        activated = validate_success(api.activate_formula(solved["id"], NUT), 200)
        assert activated["status"] == "ACTIVE"

    def test_nutrient_floor_above_solution_rejected(self, api):
        """PRD §3.4: "Activation moves `DRAFT` → `ACTIVE` and is refused unless three conditions hold: `lines` is non-empty, `meets_constraints` is true (else `ERR_NUTRIENT_CONSTRAINT_VIOLATION`), and every line ingredient is `ACTIVE` (else `ERR_INGREDIENT_NOT_ACTIVE`)."

        Design: Difficulty/boundary_precision_check/nutrient_protein_exactly_at_min_meets
        """
        self._catalog_19_5()
        formula = make_formula("F-STRICT", min_protein_pct=19.51,
                               max_fiber_pct=5.0, min_energy_kcal_kg=3000)
        solved = optimize_formula(formula)
        # 19.50 < 19.51: the inclusive floor is not met.
        assert solved["total_protein_pct"] == pytest.approx(19.5, abs=0.001)
        assert solved["meets_constraints"] is False

        resp = api.activate_formula(solved["id"], NUT)
        validate_error(resp, ApiErrorId.ERR_NUTRIENT_CONSTRAINT_VIOLATION)

        after = validate_success(api.get_formula(solved["id"], NUT), 200)
        assert after["status"] == "DRAFT"
