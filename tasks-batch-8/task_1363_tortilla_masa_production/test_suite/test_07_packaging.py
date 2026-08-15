"""Packaging: dual-variant weight verification, band boundaries, sample
cardinality, seal idempotency, and same-response visibility of mutations."""
import pytest

from test_helpers import (
    ApiErrorId,
    allocate_masa,
    create_conditioned_lot,
    create_line,
    create_nixtamal_batch_payload,
    create_pack_order,
    create_product,
    create_run,
    create_weight_check_payload,
    evaluate_batch,
    schedule_run,
    set_clock,
    setup_in_progress_run,
    setup_sealed_pack,
    start_cook,
    start_steep,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PACK = TEST_USERS["packaging_lead_headers"]
MILLER = TEST_USERS["miller_operator_headers"]


def _in_progress_run_with_two_pack_orders(api):
    """Run IN_PROGRESS (360.0 g declared pack, 2% tolerance -> band
    [352.8, 367.2]) with one AVERAGE_WEIGHT and one COUNT_VERIFY pack order,
    both in PACKING."""
    ctx = setup_in_progress_run(
        planned_cases=100, allocated_kg=388.8,
        product_overrides={"sku_code": "CORN-6-12"},
        line_overrides={"line_code": "L-WV"},
    )
    po_avg = create_pack_order(ctx["run"]["id"], cases_planned=50,
                               verification_method="AVERAGE_WEIGHT")
    po_cnt = create_pack_order(ctx["run"]["id"], cases_planned=50,
                               verification_method="COUNT_VERIFY")
    validate_success(api.start_packing(po_avg["id"], PACK))
    validate_success(api.start_packing(po_cnt["id"], PACK))
    return ctx, po_avg, po_cnt


class TestVerificationMethodDivergence:
    def test_average_weight_passes_on_in_band_samples(self, api):
        """PRD §3.7: "Under `AVERAGE_WEIGHT`, the declared pack net weight and the
        product's `weight_tolerance_pct` define an inclusive band: the lower bound
        is `declared_pack_net_g` multiplied by one minus `weight_tolerance_pct`
        divided by 100; the upper bound is `declared_pack_net_g` multiplied by one
        plus `weight_tolerance_pct` divided by 100. `avg_pack_weight_g` is the
        mean of `sample_weights_g` rounded half-up to one decimal place, and the
        check passes when the rounded average lies at or above the lower bound and
        at or below the upper bound; individual piece counts are ignored."
        Samples [360.0, 370.0, 350.0] average 360.0 inside [352.8, 367.2].

        Design: Difficulty/dual_variant_calc/pack_weight_average_vs_count_verify_diverge
        """
        _, po_avg, _ = _in_progress_run_with_two_pack_orders(api)
        checked = validate_success(
            api.weight_check(
                po_avg["id"],
                create_weight_check_payload(50, sample_weights_g=[360.0, 370.0, 350.0]),
                PACK,
            )
        )
        assert checked["pack_status"] == "PASSED"
        assert checked["avg_pack_weight_g"] == pytest.approx(360.0)

    def test_count_verify_fails_same_physical_cartons(self, api):
        """PRD §3.7: "Under `COUNT_VERIFY`, the check passes when **every** entry
        of `sample_counts` equals the product's `count_per_pack` **and** the
        average pack weight is at or above the lower bound — the upper band is not
        applied. `count_accuracy_pct` is the share of sampled packs with exactly
        `count_per_pack` pieces, expressed as a percentage to two decimal places."
        and "A failing check moves the pack order from `PACKING` to `HOLD` and
        still records the failed metrics".
        Counts [12, 13, 11] are not all 12 -> HOLD with accuracy 33.33 — the same
        cartons that passed AVERAGE_WEIGHT.

        Design: Difficulty/dual_variant_calc/pack_weight_average_vs_count_verify_diverge
        """
        _, _, po_cnt = _in_progress_run_with_two_pack_orders(api)
        checked = validate_success(
            api.weight_check(
                po_cnt["id"],
                create_weight_check_payload(
                    50,
                    sample_weights_g=[360.0, 370.0, 350.0],
                    sample_counts=[12, 13, 11],
                ),
                PACK,
            )
        )
        assert checked["pack_status"] == "HOLD"
        assert checked["count_accuracy_pct"] == pytest.approx(33.33, abs=1e-6)


class TestWeightBandBoundary:
    def test_exact_lower_bound_passes(self, api):
        """PRD §3.7: "the check passes when the rounded average lies at or above
        the lower bound and at or below the upper bound" — the bounds are
        inclusive. PRD §2.5: "In every case, rounding to the declared precision
        happens **before** any downstream band or threshold comparison".
        declared 360.0 with 2% tolerance -> lower bound 352.8; an average of
        exactly 352.8 passes.

        Design: Difficulty/boundary_precision_check/weight_check_exact_lower_bound_passes
        """
        ctx = setup_in_progress_run(
            planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "CORN-6-B1"},
            line_overrides={"line_code": "L-B1"},
        )
        pack_order = create_pack_order(ctx["run"]["id"], cases_planned=30)
        validate_success(api.start_packing(pack_order["id"], PACK))
        checked = validate_success(
            api.weight_check(
                pack_order["id"],
                create_weight_check_payload(30, sample_weights_g=[352.8, 352.8, 352.8]),
                PACK,
            )
        )
        assert checked["avg_pack_weight_g"] == pytest.approx(352.8)
        assert checked["pack_status"] == "PASSED"

    def test_one_tenth_gram_below_lower_bound_fails(self, api):
        """PRD §3.7: "the lower bound is `declared_pack_net_g` multiplied by one
        minus `weight_tolerance_pct` divided by 100" and "A failing check moves
        the pack order from `PACKING` to `HOLD` and still records the failed
        metrics — `avg_pack_weight_g` and `count_accuracy_pct` are updated even on
        failure."
        352.7 sits one 1dp step below the 352.8 lower bound -> HOLD, and the
        failing metric is still recorded.

        Design: Difficulty/boundary_precision_check/weight_check_exact_lower_bound_passes
        """
        ctx = setup_in_progress_run(
            planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "CORN-6-B1"},
            line_overrides={"line_code": "L-B1"},
        )
        pack_order = create_pack_order(ctx["run"]["id"], cases_planned=30)
        validate_success(api.start_packing(pack_order["id"], PACK))
        checked = validate_success(
            api.weight_check(
                pack_order["id"],
                create_weight_check_payload(30, sample_weights_g=[352.7, 352.7, 352.7]),
                PACK,
            )
        )
        assert checked["pack_status"] == "HOLD"
        assert checked["avg_pack_weight_g"] == pytest.approx(352.7)

    def test_sample_below_minimum_cardinality_rejected(self, api):
        """PRD §3.7: "Only the array matching the pack order's declared
        `verification_method` is evaluated; supplying the wrong array, or a sample
        with cardinality below 3, is rejected with `ERR_WEIGHT_SAMPLE_INVALID`."
        A two-pack sample fails regardless of the weights.

        Design: Corner/validations/val_weight_sample_below_minimum
        """
        ctx = setup_in_progress_run(
            planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "C-WS"},
            line_overrides={"line_code": "L-WS"},
        )
        pack_order = create_pack_order(ctx["run"]["id"], cases_planned=10)
        validate_success(api.start_packing(pack_order["id"], PACK))
        validate_error(
            api.weight_check(
                pack_order["id"],
                create_weight_check_payload(10, sample_weights_g=[360.0, 360.0]),
                PACK,
            ),
            ApiErrorId.ERR_WEIGHT_SAMPLE_INVALID,
        )
        after = validate_success(api.get_pack_order(pack_order["id"], PACK))
        assert after["pack_status"] == "PACKING"


class TestSeal:
    def test_double_seal_rejected(self, api):
        """PRD §3.7: "Sealing requires the pack order to be in `PASSED` and the
        parent run's `qc_status` to be anything other than `ON_HOLD` — sealing
        against an active QC hold is rejected with `ERR_QC_HOLD_ACTIVE`." A
        SEALED order is past PASSED, so a second seal fails the from-state check
        with ERR_PACK_INVALID_STATE (§5) and the recorded seal data is untouched.

        Design: Corner/state_machines/sm_pack_order_double_seal_rejected
        """
        ctx = setup_sealed_pack(
            cases_packed=5, planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "SM-DS"},
            line_overrides={"line_code": "L-DS"},
        )
        pack_order = ctx["pack_order"]
        assert pack_order["pack_status"] == "SEALED"
        validate_error(
            api.seal_pack_order(pack_order["id"], PACK),
            ApiErrorId.ERR_PACK_INVALID_STATE,
        )
        after = validate_success(api.get_pack_order(pack_order["id"], PACK))
        assert after["pack_status"] == "SEALED"
        assert after["sealed_at"] == pack_order["sealed_at"]
        assert after["expires_on"] == pack_order["expires_on"]


class TestImmediateVisibility:
    def test_mutations_return_computed_state_in_same_response(self, api):
        """PRD §2.7: "Mutations propagate immediately and are visible in the same
        request response." PRD §2.2: "Unless otherwise noted, operations that
        create or modify a resource will return the created or updated resource
        object in the data field." PRD §3.7: "A successful seal stamps `sealed_at`
        with the logical clock, computes `expires_on` as the ISO date `sealed_at`
        plus the product's `shelf_life_days`, initializes `cases_available` to
        `cases_packed`, and advances the pack order to terminal `SEALED`."
        Batch create already carries theoretical_masa_kg 1700.0; mill carries
        masa_available_kg 1552.0; weight-check carries PASSED + 360.0; seal
        carries SEALED + expires_on 2026-08-21 (2026-08-01 + 20 days).

        Design: Corner/consistency_model/cons_immediate_visibility_in_mutation_response
        """
        lot = create_conditioned_lot(lot_code="LOT-IM")
        batch = validate_success(
            api.create_nixtamal_batch(
                create_nixtamal_batch_payload(lot["id"], corn_kg=1000), MILLER
            ),
            201,
        )
        assert batch["theoretical_masa_kg"] == pytest.approx(1700.0), (
            "creation response already carries the provisional yield"
        )
        start_cook(batch["id"])
        set_clock("2026-08-01T02:00:00Z")
        start_steep(batch["id"])
        set_clock("2026-08-01T12:00:00Z")
        evaluate_batch(batch["id"], "PASS")
        milled = validate_success(
            api.mill_batch(
                batch["id"],
                {"milled_masa_kg": 1620, "measured_moisture_pct": 58,
                 "masa_wasted_kg": 20},
                MILLER,
            )
        )
        assert milled["masa_available_kg"] == pytest.approx(1552.0)

        product = create_product(sku_code="C-IM")
        line = create_line(line_code="L-IM")
        run = create_run(product["id"], line["id"], planned_cases=50)
        schedule_run(run["id"])
        allocate_masa(batch["id"], run["id"], 194.4)
        validate_success(api.start_run(run["id"], TEST_USERS["line_scheduler_headers"]))
        pack_order = create_pack_order(run["id"], cases_planned=10)
        validate_success(api.start_packing(pack_order["id"], PACK))
        checked = validate_success(
            api.weight_check(
                pack_order["id"],
                create_weight_check_payload(10, sample_weights_g=[360.0, 360.0, 360.0]),
                PACK,
            )
        )
        assert checked["pack_status"] == "PASSED"
        assert checked["avg_pack_weight_g"] == pytest.approx(360.0)
        sealed = validate_success(api.seal_pack_order(pack_order["id"], PACK))
        assert sealed["pack_status"] == "SEALED"
        assert sealed["expires_on"] == "2026-08-21"
