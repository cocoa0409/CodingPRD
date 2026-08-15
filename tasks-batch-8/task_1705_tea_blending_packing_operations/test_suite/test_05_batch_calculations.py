"""Batch arithmetic: dual-variant cost accounting, pinned component
scaling order, and per-line yield rounding.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    allocate,
    apply_flavoring,
    blend_batch,
    create_active_recipe,
    create_batch,
    create_flavoring,
    create_released_lot,
    create_supplier,
    finalize_allocation,
    get_batch,
    lock_recipe,
    release_batch,
    single_component,
    submit_qc,
)

BM = TEST_USERS["blend_master_headers"]


def _cost_scenario():
    """Two BLACK lots (100.0 + 50.0 kg @1200, moisture 6.0, grade A),
    CONVENTIONAL LOOSE_PACK recipe [{BLACK,B,100}], batch target 40.0 with
    allocations 28.0 + 12.0, finalized and blended at 6.2%."""
    supplier = create_supplier(name="Assam Co")
    lot1 = create_released_lot(supplier["id"], leaf_type="BLACK",
                               harvest_date="2026-01-15", weight_kg=100.0,
                               cost_per_kg_cents=1200, moisture_pct=6.0,
                               aroma_score=90, briskness_score=88,
                               appearance_score=92, measured_residue_ppm=0.30)
    lot2 = create_released_lot(supplier["id"], leaf_type="BLACK",
                               harvest_date="2026-01-20", weight_kg=50.0,
                               cost_per_kg_cents=1200, moisture_pct=6.0,
                               aroma_score=90, briskness_score=88,
                               appearance_score=92, measured_residue_ppm=0.30)
    recipe = create_active_recipe(
        name="R1", pack_format="LOOSE_PACK",
        components=[single_component("BLACK", "B", 100.0)])
    batch = create_batch(recipe["id"], 40.0)
    lock_recipe(batch["id"])
    allocate(batch["id"], lot1["id"], 28.0)
    allocate(batch["id"], lot2["id"], 12.0)
    return batch


class TestBatchCostVariants:
    def test_provisional_is_leaf_only_final_adds_waste(self, api):
        """PRD §3.4: "A successful finalization moves the batch from
        `RECIPE_LOCKED` to `ALLOCATED` and books `provisional_cost_cents`:
        the sum, over the batch's `ACTIVE` allocation lines, of each
        line's allocated kilograms multiplied by its lot's cost per
        kilogram, with every line rounded half-up to whole cents before
        the lines are summed."
        PRD §3.5: "The `final_cost_cents` extend the provisional figure:
        the `flavoring_cost_cents` across the batch's flavoring
        applications are added (zero when unflavored), a waste surcharge
        of two percent is computed on the combined leaf-and-flavoring
        subtotal and rounded half-up to whole cents, and the final cost is
        the sum of those three terms — given identical inputs, strictly
        larger than the provisional figure whenever flavoring cost or
        waste is nonzero."

        provisional = 33600 + 14400 = 48000; final = 48000 + 0 +
        round_half_up(48000 * 0.02) = 48960.

        Design: Difficulty/dual_variant_calc/batch_cost_provisional_vs_final
        """
        batch = _cost_scenario()
        finalized = finalize_allocation(batch["id"])
        assert finalized["status"] == "ALLOCATED"
        assert finalized["provisional_cost_cents"] == 48000

        blend_batch(batch["id"], measured_moisture_pct=6.2)
        submit_qc(batch["id"])
        released = release_batch(batch["id"])
        assert released["status"] == "RELEASED"
        assert released["final_cost_cents"] == 48960
        assert released["final_cost_cents"] != finalized[
            "provisional_cost_cents"], (
            "identical inputs, two variants, different cents")

    def test_actual_weight_is_yield_plus_flavoring(self, api):
        """PRD §3.5: "The batch's `actual_weight_kg` is set to its
        `yield_kg` plus its `flavoring_kg`, and the batch becomes
        `RELEASED`."
        PRD §3.5: "A lot whose moisture exceeds the 5.0 percent target
        contributes its allocated kilograms multiplied by a shrink
        factor: one minus the ratio of the lot's excess over target to
        the headroom below saturation — that is, the lot's `moisture_pct`
        minus 5.0, divided by 100 minus 5.0, subtracted from one — with
        the line result rounded half-up to three decimal places."

        Per-line yields: round_half_up(28.0 * (1 - 1/95), 3) = 27.705 and
        round_half_up(12.0 * (1 - 1/95), 3) = 11.874; yield 39.579;
        unflavored, so actual_weight_kg == 39.579.

        Design: Difficulty/dual_variant_calc/batch_cost_provisional_vs_final
        """
        batch = _cost_scenario()
        finalize_allocation(batch["id"])
        blended = blend_batch(batch["id"], measured_moisture_pct=6.2)
        assert blended["yield_kg"] == pytest.approx(39.579, abs=0.0005)
        submit_qc(batch["id"])
        released = release_batch(batch["id"])
        assert released["flavoring_kg"] == pytest.approx(0.0, abs=0.0005)
        assert released["actual_weight_kg"] == pytest.approx(39.579,
                                                             abs=0.0005)


class TestYieldPerLineRounding:
    def test_per_line_rounding_then_sum(self, api):
        """PRD §3.5: "The batch's `yield_kg` is the sum of these
        already-rounded line yields, never a rounding applied to the
        sum."

        Two 10.0 kg lines at lot moisture 6.0: each line rounds to
        9.895 kg (round_half_up(10.0 * (1 - 1/95), 3)); the batch yield
        is 19.790 kg — the sum-then-round misreading would give 19.789.

        Design: Difficulty/combinatorial_formula/yield_per_line_rounding_order
        """
        supplier = create_supplier(name="Kandy Co")
        lot_a = create_released_lot(supplier["id"], leaf_type="GREEN",
                                    harvest_date="2026-03-01",
                                    weight_kg=10.0, cost_per_kg_cents=500,
                                    moisture_pct=6.0)
        lot_b = create_released_lot(supplier["id"], leaf_type="GREEN",
                                    harvest_date="2026-03-02",
                                    weight_kg=10.0, cost_per_kg_cents=500,
                                    moisture_pct=6.0)
        recipe = create_active_recipe(
            name="R4", pack_format="TEA_BAG",
            components=[single_component("GREEN", "C", 100.0)])
        batch = create_batch(recipe["id"], 20.0)
        lock_recipe(batch["id"])
        allocate(batch["id"], lot_a["id"], 10.0)
        allocate(batch["id"], lot_b["id"], 10.0)
        finalize_allocation(batch["id"])

        blended = blend_batch(batch["id"], measured_moisture_pct=6.5)
        assert blended["yield_kg"] == pytest.approx(19.790, abs=0.0005)
        assert blended["yield_kg"] != pytest.approx(19.789, abs=0.0005), (
            "sum-then-round misreading must be excluded")

    def test_lot_at_target_moisture_contributes_full_weight(self, api):
        """PRD §3.5: "A lot at or below the 5.0 percent target contributes
        its full allocated kilograms unchanged."

        Same two-line shape at lot moisture exactly 5.0: no shrink factor
        engages, so the yield is the full 20.0 kg.

        Design: Difficulty/combinatorial_formula/yield_per_line_rounding_order
        """
        supplier = create_supplier(name="Kandy Co Dry")
        lot_a = create_released_lot(supplier["id"], leaf_type="GREEN",
                                    harvest_date="2026-03-01",
                                    weight_kg=10.0, cost_per_kg_cents=500,
                                    moisture_pct=5.0)
        lot_b = create_released_lot(supplier["id"], leaf_type="GREEN",
                                    harvest_date="2026-03-02",
                                    weight_kg=10.0, cost_per_kg_cents=500,
                                    moisture_pct=5.0)
        recipe = create_active_recipe(
            name="R4-Dry", pack_format="TEA_BAG",
            components=[single_component("GREEN", "C", 100.0)])
        batch = create_batch(recipe["id"], 20.0)
        lock_recipe(batch["id"])
        allocate(batch["id"], lot_a["id"], 10.0)
        allocate(batch["id"], lot_b["id"], 10.0)
        finalize_allocation(batch["id"])

        blended = blend_batch(batch["id"], measured_moisture_pct=5.0)
        assert blended["yield_kg"] == pytest.approx(20.0, abs=0.0005)


class TestComponentScalingOrder:
    def _scenario(self):
        supplier = create_supplier(name="Nuwara Co", origin_region="Nuwara Eliya")
        flavoring = create_flavoring(name="Bergamot Oil", allergen_tags=[],
                                     natural_certified=True,
                                     cost_per_kg_cents=3000)
        recipe = create_active_recipe(
            name="R5", pack_format="LOOSE_PACK",
            components=[single_component("BLACK", "B", 57.0),
                        single_component("GREEN", "C", 38.0)],
            flavoring_id=flavoring["id"], flavoring_pct=5.0)
        batch = create_batch(recipe["id"], 50.0)
        locked = lock_recipe(batch["id"])
        return supplier, flavoring, recipe, locked

    def test_flavoring_reserved_before_leaf_normalization(self, api):
        """PRD §3.4: "The evaluation order is pinned: the flavoring
        reservation comes first — `flavoring_kg` is the `target_weight_kg`
        multiplied by the recipe's `flavoring_pct` and divided by 100,
        rounded half-up to three decimal places — and only then is the
        leaf pool computed as the `target_weight_kg` minus the reserved
        `flavoring_kg`."

        flavoring_kg = 50.0 * 5/100 = 2.5 reserved first; the 47.5 kg
        leaf pool normalizes to BLACK 28.5 (= 47.5 * 57/95) and GREEN
        19.0 (= 47.5 * 38/95) — not the 30.0/20.0 a full-target
        normalization would give.

        Design: Difficulty/combinatorial_formula/component_scaling_evaluation_order
        """
        _, _, _, locked = self._scenario()
        assert locked["flavoring_kg"] == pytest.approx(2.5, abs=0.0005)
        by_type = {c["leaf_type"]: c for c in locked["required_components"]}
        assert by_type["BLACK"]["required_kg"] == pytest.approx(28.5,
                                                                abs=0.0005)
        assert by_type["GREEN"]["required_kg"] == pytest.approx(19.0,
                                                                abs=0.0005)

    def test_required_components_freeze_grade_and_sum_identity(self, api):
        """PRD §3.4: "Each component's `required_kg` is that leaf pool
        multiplied by the component's `pct` and divided by the sum of all
        component `pct` values, again rounded half-up to three decimal
        places, and the resulting triples of leaf type, minimum grade,
        and required kilograms are frozen into `required_components`."

        The frozen triples carry the recipe's min grades (B and C), and
        the pinned-order pool identity holds: 28.5 + 19.0 + 2.5 == 50.0.

        Design: Difficulty/combinatorial_formula/component_scaling_evaluation_order
        """
        _, _, _, locked = self._scenario()
        by_type = {c["leaf_type"]: c for c in locked["required_components"]}
        assert by_type["BLACK"]["min_grade"] == "B"
        assert by_type["GREEN"]["min_grade"] == "C"
        total = (by_type["BLACK"]["required_kg"]
                 + by_type["GREEN"]["required_kg"] + locked["flavoring_kg"])
        assert total == pytest.approx(50.0, abs=0.0005), (
            "pool identity holds only under the pinned evaluation order")


def test_final_cost_with_flavoring_literal(api):
    """PRD §3.5: "The `final_cost_cents` extend the provisional figure:
    the `flavoring_cost_cents` across the batch's flavoring applications
    are added (zero when unflavored), a waste surcharge of two percent is
    computed on the combined leaf-and-flavoring subtotal and rounded
    half-up to whole cents, and the final cost is the sum of those three
    terms"
    PRD §3.5: "A successful application persists a flavoring application
    stamped with `applied_by_user_id`, books `flavoring_cost_cents` as
    the applied kilograms multiplied by the flavoring's
    `cost_per_kg_cents` rounded half-up to whole cents"

    Leaf lines 18000 + 10500 + 15200 = 43700 provisional; flavoring
    2.5 kg x 3000 = 7500; waste round_half_up(51200 * 0.02) = 1024;
    final = 52224; actual_weight_kg = 47.5 + 2.5 = 50.0.

    Design: Corner/calculations/final_cost_with_flavoring_literal
    """
    supplier = create_supplier(name="Cost Co")
    lot1 = create_released_lot(supplier["id"], leaf_type="BLACK",
                               harvest_date="2026-02-01", weight_kg=18.0,
                               cost_per_kg_cents=1000, moisture_pct=5.0,
                               aroma_score=90, briskness_score=88,
                               appearance_score=92)
    lot2 = create_released_lot(supplier["id"], leaf_type="BLACK",
                               harvest_date="2026-02-02", weight_kg=10.5,
                               cost_per_kg_cents=1000, moisture_pct=5.0,
                               aroma_score=90, briskness_score=88,
                               appearance_score=92)
    lot3 = create_released_lot(supplier["id"], leaf_type="GREEN",
                               harvest_date="2026-02-03", weight_kg=19.0,
                               cost_per_kg_cents=800, moisture_pct=5.0)
    flavoring = create_flavoring(name="Bergamot", allergen_tags=[],
                                 natural_certified=True,
                                 cost_per_kg_cents=3000)
    recipe = create_active_recipe(
        name="RCost", pack_format="LOOSE_PACK",
        components=[single_component("BLACK", "B", 57.0),
                    single_component("GREEN", "C", 38.0)],
        flavoring_id=flavoring["id"], flavoring_pct=5.0)
    batch = create_batch(recipe["id"], 50.0)
    lock_recipe(batch["id"])
    allocate(batch["id"], lot1["id"], 18.0)
    allocate(batch["id"], lot2["id"], 10.5)
    allocate(batch["id"], lot3["id"], 19.0)

    finalized = finalize_allocation(batch["id"])
    assert finalized["provisional_cost_cents"] == 43700

    blend_batch(batch["id"], measured_moisture_pct=5.0)
    application = apply_flavoring(batch["id"], flavoring["id"], 2.5)
    assert application["flavoring_cost_cents"] == 7500

    submit_qc(batch["id"])
    released = release_batch(batch["id"])
    assert released["final_cost_cents"] == 52224
    assert released["actual_weight_kg"] == pytest.approx(50.0, abs=0.0005)
    assert released["allergen_tags"] == []
