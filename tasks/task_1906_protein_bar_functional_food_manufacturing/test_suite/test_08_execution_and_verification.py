"""Run execution and pre-run verification: dual-variant protein
substantiation, sweetener adjustment variants, changeover gating, and the
cut plan (PRD §3.4, §3.6, §3.8)."""
from test_helpers import (
    ApiErrorId,
    assert_2dp,
    fixtures,
    make_quality_manager_headers,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client
from test_helpers.test_users import TEST_USERS

QM = TEST_USERS["quality_manager_headers"]
PP = TEST_USERS["production_planner_headers"]


class TestLabelVsCompositeProtein:
    def test_label_variant_uses_nominal_assays(self, api):
        """PRD §3.4: "The batch yield in bars is the revision's
        `batch_size_kg` converted to grams and divided by the formula's
        `bar_weight_g`, rounded down to a whole number of bars. For every
        ingredient line flagged `is_protein_contributor`, the line's protein
        contribution in grams is the line's `qty_kg_per_batch` converted to
        grams and multiplied by the ingredient's `nominal_protein_pct`,
        rounded half-up to two decimal places."
        PRD §3.4: "The result is written to the revision's
        `label_protein_g_per_serving`."
        PRD §3.8: "The composite protein result is stored on the revision as
        `composite_protein_g_per_serving`, which is null until a run of that
        revision passes this gate."

        Design: Difficulty/dual_variant_calc/label_vs_composite_protein_substantiation
        """
        ns = fixtures.setup_label_composite_scenario()
        revision = validate_success(client.get_revision(ns.r1["id"], QM), 200)
        # (40000*0.80 + 10000*0.85) / floor(100000/60) = 40500/1666 -> 24.31
        assert_2dp(revision["label_protein_g_per_serving"], 24.31,
                   "label_protein_g_per_serving")
        # The run is only scheduled, not pre-run verified: composite still null.
        assert revision["composite_protein_g_per_serving"] is None

    def test_composite_variant_uses_reserved_lot_coa_assays(self, api):
        """PRD §3.8: "The composite calculation follows the same shape as the
        LABEL variant of §3.4 — same pinned rounding order, same 10.0 and 5.0
        gram-per-serving thresholds — except that each protein-contributing
        line's fraction comes from the reserved supplier lots rather than the
        nominal assay: the sum, across the run's `reserved_lot_allocations`
        entries for that ingredient, of each entry's `qty_kg` multiplied by
        its lot's `coa_protein_pct`, divided by the total reserved kilograms
        for that ingredient."
        PRD §3.8: "The composite protein result is stored on the revision as
        `composite_protein_g_per_serving`, which is null until a run of that
        revision passes this gate."

        Design: Difficulty/dual_variant_calc/label_vs_composite_protein_substantiation
        """
        ns = fixtures.setup_label_composite_scenario()
        verified = validate_success(client.verify_pre_run(ns.run1["id"], QM), 200)
        assert verified["status"] == "PRE_RUN_VERIFIED"
        revision = validate_success(client.get_revision(ns.r1["id"], QM), 200)
        # (40000*0.76 + 10000*0.85) / 1666 = 38900/1666 -> 23.35
        assert_2dp(revision["composite_protein_g_per_serving"], 23.35,
                   "composite_protein_g_per_serving")
        assert_2dp(revision["label_protein_g_per_serving"], 24.31,
                   "label_protein_g_per_serving")
        delta = revision["label_protein_g_per_serving"] - revision["composite_protein_g_per_serving"]
        assert_2dp(delta, 0.96, "label-composite delta")


class TestSweetenerAdjustmentVariants:
    def test_provisional_at_create_final_at_verify(self, api):
        """PRD §3.6: "For each line whose ingredient is a `SWEETENER`, the
        provisional requirement is the line's `qty_kg_per_batch` multiplied by
        the ingredient's `nominal_sweetness_factor` and divided by the same
        nominal factor — the line quantity itself — rounded up to the nearest
        hundredth of a kilogram, and the stored figure is the sum over all
        sweetener lines."
        PRD §3.8: "And the **FINAL variant** of the sweetener adjustment is
        stored on the run as `final_sweetener_required_kg`: for each sweetener
        line, the line's `qty_kg_per_batch` multiplied by the ingredient's
        `nominal_sweetness_factor` and divided by the reserved-lot weighted
        sweetness factor — the sum of each allocation entry's `qty_kg` times
        its lot's `coa_sweetness_factor`, divided by the total reserved
        kilograms — rounded up to the nearest hundredth of a kilogram, then
        summed over the sweetener lines."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_sweetener_factor
        """
        ns = fixtures.setup_provisional_final_scenario()
        # 10 kg * 1.0 / 1.0 -> 10.00 kg reserved at creation.
        assert_2dp(ns.run1["provisional_sweetener_required_kg"], 10.00,
                   "provisional_sweetener_required_kg")
        verified = validate_success(client.verify_pre_run(ns.run1["id"], QM), 200)
        # 10 kg * 1.0 / 0.8 -> 12.50 kg under the reserved lot's CoA factor.
        assert_2dp(verified["final_sweetener_required_kg"], 12.50,
                   "final_sweetener_required_kg")

    def test_verify_pre_run_tops_up_sweetener_reservation(self, api):
        """PRD §3.8: "When the final requirement exceeds what is already
        reserved, the run tops up its sweetener reservations by the
        difference, drawing from the same ingredient's remaining available
        `RELEASED` lots oldest-receipt first with ties broken by creation
        order; if the available quantity cannot cover the delta, the
        transition fails with `ERR_INGREDIENT_SHORTAGE`."

        Design: Difficulty/dual_variant_calc/provisional_vs_final_sweetener_factor
        """
        ns = fixtures.setup_provisional_final_scenario()
        verified = validate_success(client.verify_pre_run(ns.run1["id"], QM), 200)
        assert verified["status"] == "PRE_RUN_VERIFIED"
        lot = validate_success(client.get_ingredient_lot(ns.sl["id"], QM), 200)
        # 10.00 reserved at creation + 2.50 topped up at verification.
        assert_2dp(lot["reserved_qty_kg"], 12.50, "reserved_qty_kg")


class TestPreRunChangeoverGate:
    def test_verify_rejected_while_changeover_not_validated(self, api):
        """PRD §3.8: "Second, the changeover event feeding this run must stand
        in `VALIDATED` (`ERR_CHANGEOVER_NOT_VALIDATED`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/verify_pre_run_requires_validated_changeover
        """
        ns = fixtures.setup_swab_gated_run(swab_ppm=10, swab_user_id="lt-001")
        # Control: carryover {MILK, WHEAT} spans two allergens -> SWAB_VALIDATE.
        assert ns.co_b["required_level"] == "SWAB_VALIDATE"
        # Changeover sits in SWAB_RECORDED: the run cannot verify yet.
        resp = client.verify_pre_run(ns.run_b["id"], QM)
        validate_error(resp, ApiErrorId.ERR_CHANGEOVER_NOT_VALIDATED, 422)

    def test_verify_succeeds_after_changeover_validated(self, api):
        """PRD §3.8: "Before a scheduled run may start, a `QualityManager`
        performs pre-run verification, moving the run from `SCHEDULED` to
        `PRE_RUN_VERIFIED`."
        PRD §3.8: "Second, the changeover event feeding this run must stand
        in `VALIDATED` (`ERR_CHANGEOVER_NOT_VALIDATED`, HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/verify_pre_run_requires_validated_changeover
        """
        ns = fixtures.setup_swab_gated_run(swab_ppm=10, swab_user_id="lt-001")
        validated = validate_success(
            client.validate_changeover(ns.co_b["id"],
                                       make_quality_manager_headers("qm-001")),
            200,
        )
        assert validated["status"] == "VALIDATED"
        verified = validate_success(client.verify_pre_run(ns.run_b["id"], QM), 200)
        assert verified["status"] == "PRE_RUN_VERIFIED"


class TestCompositeSubstantiationGate:
    def test_composite_claim_unsubstantiated_at_pre_run(self, api):
        """PRD §3.8: "First, the **COMPOSITE variant** of the protein
        substantiation must satisfy every `NUTRIENT_CONTENT` claim in the
        revision's `claim_tags`, otherwise the verification is rejected with
        `ERR_COMPOSITE_CLAIM_UNSUBSTANTIATED` (HTTP 422)."

        Design: Corner/validations/c_composite_claim_unsubstantiated_at_pre_run
        """
        plant = fixtures.setup_basic_plant(whey_coa=0.2,
                                           claim_tags=["HIGH_PROTEIN"],
                                           revision_target=19)
        # Control: nominal 0.80 gives 19.21 g/serving, so LABEL passed.
        revision = validate_success(client.get_revision(plant.r1["id"], QM), 200)
        assert_2dp(revision["label_protein_g_per_serving"], 19.21,
                   "label_protein_g_per_serving")
        ns = fixtures.setup_run_scheduled(plant=plant, planned_cases=100)
        # Reserved lot's CoA is 0.20: 40000*0.20/1666 = 4.80 < 10.0.
        resp = client.verify_pre_run(ns.run["id"], QM)
        validate_error(resp, ApiErrorId.ERR_COMPOSITE_CLAIM_UNSUBSTANTIATED, 422)
        stayed = validate_success(client.get_production_run(ns.run["id"], QM), 200)
        assert stayed["status"] == "SCHEDULED"


class TestStateBeatsSafetyOnVerifyPreRun:
    def test_verify_pre_run_on_planned_run_returns_invalid_state(self, api):
        """PRD §2.6: "Only after all nine generic stages pass are the
        endpoint-specific business rules evaluated, in the explicit
        per-endpoint orders stated throughout §3."
        PRD §2.6: "9. **State-machine legality** — the resource's own state
        machine must permit the requested transition from its current state,
        else `ERR_INVALID_STATE` (409)."
        PRD §3.8: "Before a scheduled run may start, a `QualityManager`
        performs pre-run verification, moving the run from `SCHEDULED` to
        `PRE_RUN_VERIFIED`."

        Design: Corner/validations/c_state_beats_safety_on_verify_pre_run
        """
        plant = fixtures.setup_basic_plant()
        run = fixtures.create_run(plant.r1["id"], plant.ag["id"],
                                  plant.ln1["id"], 100)
        # The run is PLANNED (never scheduled): its own state machine rejects
        # before any pre-run safety gate is evaluated.
        resp = client.verify_pre_run(run["id"], QM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestCutPlan:
    def test_expected_cases_floors_per_slab_before_multiplying(self, api):
        """PRD §3.8: "The completion first computes the run's cut plan: the
        batch yields a whole number of slabs — the revision's `batch_size_kg`
        divided by the line's `slab_weight_kg`, rounded down; each slab yields
        a whole number of sellable bars — the slab weight converted to grams,
        reduced by the four percent trim allowance, divided by the formula's
        `bar_weight_g`, and rounded down; total bars are the bars per slab
        multiplied by the slab count, with the per-slab floor applied before
        the multiplication because flooring only at the end would overstate
        the count and is not the specification; and the expected case count is
        the total bars divided by twelve bars per case, rounded down."
        PRD §3.8: "Completion also creates the run's **LotRelease** — exactly
        one per run — with `qc_disposition` `PENDING` and `decision`
        `PENDING`, carrying the computed `expected_cases` and the computed
        `yield_variance_pct`"

        Design: Difficulty/combinatorial_formula/cut_plan_per_slab_floor_ordering
        """
        ns = fixtures.setup_completed_run(
            planned_cases=130, produced_cases=130, slab_weight_kg=7,
            line_name="L7",
        )
        # floor(7000*0.96/60)=112 bars/slab; floor(100/7)=14 slabs;
        # 112*14=1568 bars; floor(1568/12)=130 cases. Flooring only at the end
        # would give floor(100000*0.96/60/12)=133 — explicitly not the spec.
        assert ns.release["expected_cases"] == 130

    def test_lot_release_created_pending_with_yield_variance(self, api):
        """PRD §3.8: "Completion also creates the run's **LotRelease** —
        exactly one per run — with `qc_disposition` `PENDING` and `decision`
        `PENDING`, carrying the computed `expected_cases` and the computed
        `yield_variance_pct`: the difference between `produced_cases` and
        `planned_cases`, divided by `planned_cases`, expressed as a
        percentage, and rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/cut_plan_per_slab_floor_ordering
        """
        ns = fixtures.setup_completed_run(
            planned_cases=130, produced_cases=130, slab_weight_kg=7,
            line_name="L7",
        )
        assert ns.release["qc_disposition"] == "PENDING"
        assert ns.release["decision"] == "PENDING"
        # (130 - 130) / 130 * 100 -> 0.00
        assert_2dp(ns.release["yield_variance_pct"], 0.00, "yield_variance_pct")

    def test_produced_cases_above_cut_plan_rejected(self, api):
        """PRD §3.8: "The run's `produced_cases` must not exceed this expected
        count, else completion is rejected with
        `ERR_OUTPUT_EXCEEDS_CUT_PLAN` (HTTP 422) — the plant cannot sell more
        bars than the dough yields."

        Design: Corner/validations/c_output_exceeds_cut_plan
        """
        ns = fixtures.setup_run_in_production(planned_cases=130)
        # Default line slab 20 kg, batch 100 kg: expected floor(320*5/12)=133.
        resp = client.complete_run(
            ns.run["id"], {"produced_cases": 134, "scrapped_cases": 0}, PP
        )
        validate_error(resp, ApiErrorId.ERR_OUTPUT_EXCEEDS_CUT_PLAN, 422)
        stayed = validate_success(client.get_production_run(ns.run["id"], PP), 200)
        assert stayed["status"] == "IN_PRODUCTION"
