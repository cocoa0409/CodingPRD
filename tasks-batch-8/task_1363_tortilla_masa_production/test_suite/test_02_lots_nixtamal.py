"""Corn lots and nixtamalization: draw-down accounting, cook/steep timing gates,
recook cycle, dual-variant masa yield."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_ingredient_lot,
    assert_nixtamal_batch,
    create_batch,
    create_conditioned_lot,
    create_lot,
    create_nixtamal_batch_payload,
    evaluate_batch,
    set_clock,
    setup_milled_batch,
    setup_steeping_batch,
    start_cook,
    start_steep,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
MILLER = TEST_USERS["miller_operator_headers"]
QI = TEST_USERS["quality_inspector_headers"]
SCHED = TEST_USERS["line_scheduler_headers"]


class TestLotDrawdown:
    def test_lot_auto_depletes_at_zero_available(self, api):
        """PRD §3.1: "When a batch draw pushes `available_kg` to exactly zero, the
        lot auto-transitions from `CONDITIONED` to terminal `DEPLETED` without any
        explicit action." PRD §3.2: "`theoretical_masa_kg` is `corn_kg` multiplied
        by a variety yield factor looked up from the linked lot's `corn_variety` —
        1.70 for `WHITE_CORN`, 1.65 for `YELLOW_CORN`, 1.60 for `BLUE_CORN` —
        rounded half-up to two decimal places."
        Drawing the full 1000 kg of a BLUE_CORN lot: available 0 -> DEPLETED;
        theoretical yield 1000 x 1.60 = 1600.0.

        Design: Corner/entities/entities_lot_auto_depletes_at_zero
        """
        lot = create_conditioned_lot(
            lot_code="LOT-DEP", corn_variety="BLUE_CORN", received_kg=1000,
            moisture_pct=14.0,
        )
        batch = validate_success(
            api.create_nixtamal_batch(
                create_nixtamal_batch_payload(lot["id"], corn_kg=1000), MILLER
            ),
            201,
        )
        assert batch["theoretical_masa_kg"] == pytest.approx(1600.0)
        after = validate_success(api.get_ingredient_lot(lot["id"], MILLER))
        assert_ingredient_lot(after)
        assert after["drawn_kg"] == pytest.approx(1000)
        assert after["available_kg"] == pytest.approx(0)
        assert after["lot_status"] == "DEPLETED"

    def test_lot_derived_fields_reconcile_on_each_draw(self, api):
        """PRD §3.1: "`drawn_kg` is the sum of `corn_kg` over all non-`REJECTED`
        batches that name this lot as their `ingredient_lot_id`. `available_kg` is
        `received_kg` minus `drawn_kg` and is never negative."
        Draws of 1000 then 500 kg against 5000 kg: drawn 1500, available 3500, and
        the lot stays CONDITIONED because availability has not reached zero.

        Design: Corner/cross_cutting_layers/cc_derived_lot_fields_reconcile_on_draw
        """
        lot = create_conditioned_lot(lot_code="LOT-DR", received_kg=5000)
        validate_success(
            api.create_nixtamal_batch(
                create_nixtamal_batch_payload(lot["id"], corn_kg=1000), MILLER
            ),
            201,
        )
        validate_success(
            api.create_nixtamal_batch(
                create_nixtamal_batch_payload(lot["id"], corn_kg=500), MILLER
            ),
            201,
        )
        after = validate_success(api.get_ingredient_lot(lot["id"], MILLER))
        assert after["drawn_kg"] == pytest.approx(1500)
        assert after["available_kg"] == pytest.approx(3500)
        assert after["lot_status"] == "CONDITIONED"

    def test_batch_create_with_dangling_lot_reference_not_found(self, api):
        """PRD §2.9: "Existence — path ids and foreign-key references resolve
        (`ERR_NOT_FOUND`)." Creating a batch against a nonexistent ingredient lot
        is rejected before any state logic runs.

        Design: Corner/entities/entities_fk_reference_must_exist
        """
        validate_error(
            api.create_nixtamal_batch(
                create_nixtamal_batch_payload(NON_EXISTENT_UUID, corn_kg=100), MILLER
            ),
            ApiErrorId.ERR_NOT_FOUND,
        )


class TestBatchTimingGates:
    def test_start_cook_requires_conditioned_lot(self, api):
        """PRD §3.2: "The batch must be in `PLANNED` — otherwise
        `ERR_BATCH_INVALID_STATE` — and the linked lot must be in `CONDITIONED` —
        otherwise `ERR_LOT_INVALID_STATE`."
        Lot left in RECEIVED: start-cook fails and the batch stays PLANNED.

        Design: Corner/errors/err_lot_not_conditioned_blocks_cook
        """
        lot = create_lot(lot_code="LOT-NC")
        batch = create_batch(lot["id"], corn_kg=500)
        validate_error(api.start_cook(batch["id"], MILLER), ApiErrorId.ERR_LOT_INVALID_STATE)
        after = validate_success(api.get_nixtamal_batch(batch["id"], MILLER))
        assert after["batch_status"] == "PLANNED"

    def test_start_steep_before_cook_elapsed_rejected(self, api):
        """PRD §3.2: "The batch must be in `COOKING`, and the logical clock must
        show at least `cook_minutes` elapsed since `cook_started_at`; an early
        attempt is rejected with `ERR_COOK_INCOMPLETE`."
        Clock advanced only 30 minutes into a 90-minute cook.

        Design: Corner/validations/val_cook_incomplete_blocks_steep
        """
        lot = create_conditioned_lot(lot_code="LOT-CK")
        batch = create_batch(lot["id"], corn_kg=500)
        start_cook(batch["id"])
        set_clock("2026-08-01T00:30:00Z")
        validate_error(
            api.start_steep(batch["id"], MILLER), ApiErrorId.ERR_COOK_INCOMPLETE
        )
        after = validate_success(api.get_nixtamal_batch(batch["id"], MILLER))
        assert after["batch_status"] == "COOKING"

    def test_evaluate_before_steep_elapsed_rejected(self, api):
        """PRD §3.2: "The batch must be in `STEEPING` and the logical clock must
        show at least `steep_target_hours` elapsed since `steep_started_at`; an
        early evaluation is rejected with `ERR_STEEP_INCOMPLETE`."
        Clock advanced 5 hours into an 8-hour steep.

        Design: Corner/validations/val_steep_incomplete_blocks_evaluate
        """
        lot = create_conditioned_lot(lot_code="LOT-ST")
        batch = create_batch(lot["id"], corn_kg=500)
        start_cook(batch["id"])
        set_clock("2026-08-01T02:00:00Z")
        start_steep(batch["id"])
        set_clock("2026-08-01T07:00:00Z")
        validate_error(
            api.evaluate_batch(batch["id"], "PASS", QI),
            ApiErrorId.ERR_STEEP_INCOMPLETE,
        )
        after = validate_success(api.get_nixtamal_batch(batch["id"], QI))
        assert after["batch_status"] == "STEEPING"

    def test_rejected_batch_accepts_no_further_transitions(self, api):
        """PRD §3.2: "The evaluation carries a `decision`: `PASS` advances the
        batch to `MILLING`; `RECOOK` loops the batch back to `COOKING`, increments
        `recook_count` by one, and resets `cook_started_at` to the current logical
        clock (the steep clock resets on the recook loop); `REJECT` drives the
        batch to terminal `REJECTED`." and "The batch must be in `PLANNED` —
        otherwise `ERR_BATCH_INVALID_STATE`".

        Design: Corner/state_machines/sm_batch_terminal_rejected_lockdown
        """
        ctx = setup_steeping_batch(
            lot_overrides={"lot_code": "LOT-TL"}, batch_overrides={"corn_kg": 500}
        )
        batch = evaluate_batch(ctx["batch"]["id"], "REJECT")
        assert batch["batch_status"] == "REJECTED"
        validate_error(
            api.start_cook(batch["id"], MILLER), ApiErrorId.ERR_BATCH_INVALID_STATE
        )
        after = validate_success(api.get_nixtamal_batch(batch["id"], MILLER))
        assert after["batch_status"] == "REJECTED"


class TestMasaYieldDualVariant:
    def test_theoretical_yield_computed_at_creation(self, api):
        """PRD §3.2: "Creation computes the batch's provisional yield:
        `theoretical_masa_kg` is `corn_kg` multiplied by a variety yield factor
        looked up from the linked lot's `corn_variety` — 1.70 for `WHITE_CORN`,
        1.65 for `YELLOW_CORN`, 1.60 for `BLUE_CORN` — rounded half-up to two
        decimal places." and "`yield_variance_pct` is the difference between
        `actual_masa_kg` and `theoretical_masa_kg`, divided by
        `theoretical_masa_kg`, multiplied by 100, rounded half-up to two decimal
        places; it remains null until mill."
        1000 kg WHITE_CORN -> 1700.0 provisional; variance null before mill.

        Design: Difficulty/dual_variant_calc/masa_yield_theoretical_vs_actual_diverge
        """
        lot = create_conditioned_lot(lot_code="LOT-Y1", received_kg=5000)
        batch = validate_success(
            api.create_nixtamal_batch(
                create_nixtamal_batch_payload(lot["id"], corn_kg=1000), MILLER
            ),
            201,
        )
        assert_nixtamal_batch(batch)
        assert batch["theoretical_masa_kg"] == pytest.approx(1700.0)
        assert batch["yield_variance_pct"] is None, "variance remains null until mill"

    def test_actual_yield_diverges_from_theoretical_at_mill(self, api):
        """PRD §3.2: "The final yield differs from the provisional one: net milled
        kilograms are `milled_masa_kg` minus `masa_wasted_kg`; a moisture penalty
        is computed as the amount by which `measured_moisture_pct` exceeds the
        target masa moisture of 55 percent, divided by 100, floored at zero (so a
        batch milled at or below target carries no penalty); `actual_masa_kg` is
        the net milled kilograms multiplied by one minus the moisture penalty,
        rounded half-up to two decimal places."
        Same batch: theoretical 1700.0 vs actual (1620-20) x (1-0.03) = 1552.0;
        variance (1552.0-1700.0)/1700.0 x 100 = -8.71.

        Design: Difficulty/dual_variant_calc/masa_yield_theoretical_vs_actual_diverge
        """
        ctx = setup_milled_batch(lot_overrides={"lot_code": "LOT-Y1"})
        batch = ctx["batch"]
        assert batch["batch_status"] == "MASA_AVAILABLE"
        assert batch["theoretical_masa_kg"] == pytest.approx(1700.0)
        assert batch["actual_masa_kg"] == pytest.approx(1552.0)
        assert batch["yield_variance_pct"] == pytest.approx(-8.71, abs=1e-6)
        assert batch["masa_available_kg"] == pytest.approx(1552.0)
        assert batch["theoretical_masa_kg"] != batch["actual_masa_kg"]

    def test_theoretical_yield_rounds_half_up_two_decimals(self, api):
        """PRD §2.5: "Quantities expressed to two decimal places —
        `theoretical_masa_kg`, `actual_masa_kg`, `masa_wasted_kg`,
        `masa_available_kg`, `yield_variance_pct`, `masa_required_kg`,
        `count_accuracy_pct` — are rounded **half-up to 2 decimal places**."
        2.5 kg x 1.65 (YELLOW_CORN) = 4.125 -> 4.13 (a banker's rounding would
        give 4.12).

        Design: Corner/calculations/calc_yield_rounding_half_up_precision
        """
        lot = create_conditioned_lot(
            lot_code="LOT-RND", corn_variety="YELLOW_CORN", received_kg=100,
            moisture_pct=13.0,
        )
        batch = validate_success(
            api.create_nixtamal_batch(
                create_nixtamal_batch_payload(lot["id"], corn_kg=2.5), MILLER
            ),
            201,
        )
        assert batch["theoretical_masa_kg"] == pytest.approx(4.13, abs=1e-9)


class TestRecookCycle:
    def test_recook_loops_back_to_cooking_and_counts(self, api):
        """PRD §3.2: "`RECOOK` loops the batch back to `COOKING`, increments
        `recook_count` by one, and resets `cook_started_at` to the current logical
        clock (the steep clock resets on the recook loop)".
        800 kg YELLOW_CORN -> theoretical 800 x 1.65 = 1320.0; after RECOOK the
        batch is COOKING with recook_count 1.

        Design: Difficulty/non_linear_state_machine/nixtamal_batch_recook_cycle
        """
        ctx = setup_steeping_batch(
            lot_overrides={
                "lot_code": "LOT-RC", "corn_variety": "YELLOW_CORN",
                "received_kg": 3000, "moisture_pct": 13.0,
            },
            batch_overrides={"corn_kg": 800, "lime_pct": 1.2},
        )
        batch = validate_success(
            api.evaluate_batch(ctx["batch"]["id"], "RECOOK", QI)
        )
        assert batch["batch_status"] == "COOKING"
        assert batch["recook_count"] == 1
        assert batch["theoretical_masa_kg"] == pytest.approx(1320.0)

    def test_recook_resets_clocks_then_passes_second_evaluation(self, api):
        """PRD §3.2: "`RECOOK` loops the batch back to `COOKING`, increments
        `recook_count` by one, and resets `cook_started_at` to the current logical
        clock (the steep clock resets on the recook loop)" and "`PASS` advances
        the batch to `MILLING`".
        After RECOOK at 12:00, advancing to 14:00 satisfies the fresh 90-minute
        cook; a second steep then lets PASS reach MILLING.

        Design: Difficulty/non_linear_state_machine/nixtamal_batch_recook_cycle
        """
        ctx = setup_steeping_batch(
            lot_overrides={
                "lot_code": "LOT-RC", "corn_variety": "YELLOW_CORN",
                "received_kg": 3000, "moisture_pct": 13.0,
            },
            batch_overrides={"corn_kg": 800, "lime_pct": 1.2},
        )
        validate_success(api.evaluate_batch(ctx["batch"]["id"], "RECOOK", QI))
        set_clock("2026-08-01T14:00:00Z")
        batch = start_steep(ctx["batch"]["id"])
        assert batch["batch_status"] == "STEEPING", (
            "start-steep succeeds only because cook_started_at reset at recook"
        )
        set_clock("2026-08-02T00:00:00Z")
        batch = evaluate_batch(ctx["batch"]["id"], "PASS")
        assert batch["batch_status"] == "MILLING"
        assert batch["recook_count"] == 1
