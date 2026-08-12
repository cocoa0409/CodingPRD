"""Drying batches, routing gates, processing runs, and lot grading."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_completed_drying_batch,
    create_completed_run,
    create_dryer,
    create_drying_batch_payload,
    create_graded_lot,
    create_grower,
    create_lot,
    create_processed_lot,
    create_processing_run,
    create_routed_lot,
    create_sampled_lot,
    get_lot,
    make_admin_headers,
    make_intake_headers,
    make_operator_headers,
    record_aflatoxin,
    record_kernel_grade,
    record_moisture_kernel,
    route_lot,
    set_clock,
    validate_error,
    validate_success,
)


class TestRoutingGates:
    def test_route_requires_recorded_lab_tests(self, api):
        """PRD (Routing Decisions): "The lot must be `GRADED`; any other state
        draws `ERR_INVALID_STATE`, and a terminal lot draws
        `ERR_ALREADY_TERMINAL`. The latest recorded aflatoxin test must exist
        with a `PASS` verdict".

        Design: Difficulty/cross_entity_state_dependency/route_requires_recorded_lab_tests
        """
        _, lot = create_sampled_lot(gross_weight_lbs=2000)
        resp = api.route_lot(lot["id"], {"route": "KERNEL"}, make_intake_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        record_aflatoxin(lot["id"], aflatoxin_ppb=1.0)
        assert get_lot(lot["id"])["status"] == "GRADED"
        resp2 = api.route_lot(lot["id"], {"route": "KERNEL"}, make_intake_headers())
        data = validate_success(resp2)
        assert data["status"] == "ROUTED_KERNEL"

    def test_route_after_grading_unblocked_by_aflatoxin_pass(self, api):
        """PRD (Routing Decisions): "Once a lot is `GRADED`, an
        `IntakeOperator` routes it by supplying a `route` of `IN_SHELL` or
        `KERNEL`, moving the lot to `ROUTED_IN_SHELL` or `ROUTED_KERNEL`
        respectively."

        Design: Difficulty/cross_entity_state_dependency/route_requires_recorded_lab_tests
        """
        _, lot = create_graded_lot(gross_weight_lbs=2000)
        resp = api.route_lot(lot["id"], {"route": "IN_SHELL"}, make_intake_headers())
        data = validate_success(resp)
        assert data["status"] == "ROUTED_IN_SHELL"

    def test_route_state_vs_aflatoxin_safety(self, api):
        """PRD (Validation Order): "when a request violates rules from several
        of the ten categories below, the violation belonging to the earliest
        category is the one reported" — state preconditions (category 6) precede
        safety lockouts (category 7): routing a SAMPLED lot that also lacks any
        aflatoxin result reports ERR_INVALID_STATE, never the safety error.

        Design: Difficulty/priority_pair_validation_conflict/route_state_vs_aflatoxin_safety
        """
        _, lot = create_sampled_lot(gross_weight_lbs=3000)
        resp = api.route_lot(lot["id"], {"route": "KERNEL"}, make_intake_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_lot(lot["id"])["status"] == "SAMPLED"

    def test_route_graded_lot_missing_aflatoxin_verdict_is_masked_by_state(self, api):
        """PRD (Validation Order): "when a request violates rules from several
        of the ten categories below, the violation belonging to the earliest
        category is the one reported" — state preconditions (category 6) precede
        "Aflatoxin clearance for routing (`ERR_AFLATOXIN_UNRESOLVED`, 422)"
        (category 7), so a lot that never reached GRADED cannot surface the
        aflatoxin error.

        Design: Difficulty/priority_pair_validation_conflict/route_state_vs_aflatoxin_safety
        """
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=3000)
        # RECEIVED (no lab tests at all): state gate fires first.
        resp = api.route_lot(lot["id"], {"route": "KERNEL"}, make_intake_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_route_without_completed_drying_returns_drying_required(self, api):
        """PRD (Routing Decisions): "when the lot's requires_drying flag is true,
        routing is refused with ERR_DRYING_REQUIRED until at least one drying
        batch for the lot has reached COMPLETED."

        Design: Corner/validations/route_without_completed_drying_returns_drying_required
        """
        _, lot = create_graded_lot(
            gross_weight_lbs=2000, moisture_pct=9.0, kernel_pct=0.50,
            foreign_material_pct=0.01,
        )
        assert get_lot(lot["id"])["requires_drying"] is True
        resp = api.route_lot(lot["id"], {"route": "KERNEL"}, make_intake_headers())
        validate_error(resp, ApiErrorId.ERR_DRYING_REQUIRED)
        assert get_lot(lot["id"])["status"] == "GRADED"

    def test_invalid_enum_route_value_rejected(self, api):
        """PRD (Validation Order): "Required fields are present, types are
        correct, enum values belong to their declared sets, and the
        test-type-conditional field rules on lab-test recording hold; otherwise
        `ERR_INVALID_REQUEST` (400), or `ERR_INVALID_ENUM` (400) specifically
        for enum membership failures."
        PRD (Routing Decisions): a `route` of `IN_SHELL` or `KERNEL`.

        Design: Corner/errors/invalid_enum_route_value_rejected
        """
        _, lot = create_graded_lot(gross_weight_lbs=2000)
        resp = api.route_lot(lot["id"], {"route": "WHOLE"}, make_intake_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_ENUM, expected_status=400)
        assert get_lot(lot["id"])["status"] == "GRADED"


class TestDryingBatches:
    def test_dryer_half_open_adjacency_allows_touching_windows(self, api):
        """PRD (Drying Operations): "Adjacent bookings do not conflict: a new
        batch beginning exactly at an existing batch's end_at is legal".
        Dryer windows are half-open intervals: [start_at, end_at).

        Design: Difficulty/resource_temporal_overlap/dryer_half_open_adjacency
        """
        grower = create_grower()
        lot_a = create_lot(grower["id"], gross_weight_lbs=2000)
        record_moisture_kernel(lot_a["id"], moisture_pct=10.0)
        lot_b = create_lot(grower["id"], variety="Butte", gross_weight_lbs=2000)
        record_moisture_kernel(lot_b["id"], moisture_pct=10.0)
        dryer = create_dryer()
        api_client_batch = api.create_drying_batch(
            create_drying_batch_payload(
                dryer_id=dryer["id"], lot_id=lot_a["id"],
                start_at="2026-05-02T00:00:00Z", end_at="2026-05-04T00:00:00Z",
            ),
            make_operator_headers(),
        )
        validate_success(api_client_batch, expected_status=201)
        resp = api.create_drying_batch(
            create_drying_batch_payload(
                dryer_id=dryer["id"], lot_id=lot_b["id"],
                start_at="2026-05-04T00:00:00Z", end_at="2026-05-06T00:00:00Z",
            ),
            make_operator_headers(),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_dryer_overlapping_window_conflicts(self, api):
        """PRD (Drying Operations): "A new batch conflicts with an existing one
        on the same dryer when the existing batch is SCHEDULED or DRYING and the
        two windows genuinely overlap ... Conflicting reservations are rejected
        with ERR_DRYER_TIME_CONFLICT (409)."

        Design: Difficulty/resource_temporal_overlap/dryer_half_open_adjacency
        """
        grower = create_grower()
        lot_a = create_lot(grower["id"], gross_weight_lbs=2000)
        record_moisture_kernel(lot_a["id"], moisture_pct=10.0)
        lot_c = create_lot(grower["id"], variety="Carmel", gross_weight_lbs=2000)
        record_moisture_kernel(lot_c["id"], moisture_pct=10.0)
        dryer = create_dryer()
        validate_success(
            api.create_drying_batch(
                create_drying_batch_payload(
                    dryer_id=dryer["id"], lot_id=lot_a["id"],
                    start_at="2026-05-02T00:00:00Z", end_at="2026-05-04T00:00:00Z",
                ),
                make_operator_headers(),
            ),
            expected_status=201,
        )
        resp = api.create_drying_batch(
            create_drying_batch_payload(
                dryer_id=dryer["id"], lot_id=lot_c["id"],
                start_at="2026-05-03T00:00:00Z", end_at="2026-05-05T00:00:00Z",
            ),
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_DRYER_TIME_CONFLICT, expected_status=409)

    def test_batch_start_before_window_returns_not_open(self, api):
        """PRD (Drying Operations): "Starting moves SCHEDULED to DRYING and is
        only permitted once the logical clock has reached start_at; an early
        start is rejected with ERR_SCHEDULE_WINDOW_NOT_OPEN (422)."

        Design: Corner/validations/batch_start_before_window_returns_not_open
        """
        grower = create_grower()
        lot = create_lot(grower["id"], gross_weight_lbs=2000)
        record_moisture_kernel(lot["id"], moisture_pct=10.0)
        dryer = create_dryer()
        batch = validate_success(
            api.create_drying_batch(
                create_drying_batch_payload(
                    dryer_id=dryer["id"], lot_id=lot["id"],
                    start_at="2026-05-05T00:00:00Z", end_at="2026-05-06T00:00:00Z",
                ),
                make_operator_headers(),
            ),
            expected_status=201,
        )
        # Clock still at its 2026-05-01 startup default, before start_at.
        resp = api.start_drying_batch(batch["id"], make_operator_headers())
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_WINDOW_NOT_OPEN, expected_status=422)
        refreshed = validate_success(
            api.get_drying_batch(batch["id"], make_operator_headers())
        )
        assert refreshed["status"] == "SCHEDULED"


class TestProcessingRuns:
    def test_run_completion_outputs_exceeding_input_rejected(self, api):
        """PRD (Routing Decisions and Hulling Runs): "the three outputs summed
        together may not exceed the run's input_weight_lbs; a completion whose
        outputs exceed the snapshot is rejected with ERR_SHRINK_NEGATIVE".

        Design: Corner/validations/run_completion_outputs_exceeding_input_rejected
        """
        _, lot = create_routed_lot(gross_weight_lbs=3000)
        run = create_processing_run(lot["id"])
        assert run["input_weight_lbs"] == pytest.approx(3000, abs=0.01)
        validate_success(api.start_processing_run(run["id"], make_operator_headers()))
        resp = api.complete_processing_run(
            run["id"],
            {"kernel_out_lbs": 2000, "shell_out_lbs": 800, "hull_out_lbs": 500},
            make_operator_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_SHRINK_NEGATIVE)
        refreshed = validate_success(
            api.get_processing_run(run["id"], make_operator_headers())
        )
        assert refreshed["status"] == "RUNNING"

    def test_kernel_out_excludes_cancelled_runs(self, api):
        """PRD (Routing Decisions and Hulling Runs): the lot's harvest
        accumulators are "the sums of the corresponding outputs over the lot's
        COMPLETED runs only — queued, running, and cancelled runs never
        contribute."

        Design: Corner/calculations/kernel_out_excludes_cancelled_runs
        """
        _, lot = create_routed_lot(gross_weight_lbs=4000)
        run1 = create_processing_run(lot["id"])
        validate_success(api.cancel_processing_run(run1["id"], make_operator_headers()))
        run1_after = validate_success(
            api.get_processing_run(run1["id"], make_operator_headers())
        )
        assert run1_after["status"] == "CANCELLED"

        run2 = create_processing_run(lot["id"])
        validate_success(api.start_processing_run(run2["id"], make_operator_headers()))
        validate_success(
            api.complete_processing_run(
                run2["id"],
                {"kernel_out_lbs": 1500, "shell_out_lbs": 1000, "hull_out_lbs": 500},
                make_operator_headers(),
            )
        )
        updated = get_lot(lot["id"])
        assert updated["kernel_out_lbs"] == pytest.approx(1500, abs=0.01)
        assert updated["status"] == "PROCESSED"


class TestKernelWeightDualVariant:
    def _setup_full_lot(self, api):
        """10000-lb lot, intake 10.0/0.65/0.02, dried to 6.0, one completed
        run 6000/2000/1500, KERNEL_GRADE edible 0.90."""
        grower = create_grower(base_price_cents_per_lb=250, premium_rate_pct=0.10)
        lot = create_lot(grower["id"], gross_weight_lbs=10000)
        record_moisture_kernel(
            lot["id"], moisture_pct=10.0, kernel_pct=0.65, foreign_material_pct=0.02
        )
        record_aflatoxin(lot["id"], aflatoxin_ppb=5.0)
        create_completed_drying_batch(lot["id"], final_moisture_pct=6.0)
        route_lot(lot["id"], route="KERNEL")
        create_completed_run(
            lot["id"], kernel_out_lbs=6000, shell_out_lbs=2000, hull_out_lbs=1500
        )
        record_kernel_grade(lot["id"], edible_kernel_pct=0.90, size_spec="SPEC_23_25")
        return grower, get_lot(lot["id"])

    def test_provisional_and_final_kernel_weights_both_pinned(self, api):
        """PRD (Field Lot Intake): "provisional_kernel_lbs, computed as the
        lot's gross_weight_lbs multiplied by its intake_kernel_pct, multiplied
        by one minus intake_fm_pct, and then discounted by one percent for every
        full point of intake moisture above the 8.0 percent standard".
        PRD (Routing Decisions and Hulling Runs): "the lot's
        `graded_kernel_weight_lbs`: the sum of `kernel_out_lbs` over the lot's
        `COMPLETED` runs multiplied by the test's `edible_kernel_pct`, rounded
        half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/kernel_weight_provisional_vs_final
        """
        _, lot = self._setup_full_lot(api)
        # provisional: 10000 * 0.65 * (1-0.02) * (1 - 0.01*(10.0-8.0)) = 6242.60
        assert lot["provisional_kernel_lbs"] == pytest.approx(6242.60, abs=0.01)
        # final: 6000 * 0.90 = 5400.00
        assert lot["graded_kernel_weight_lbs"] == pytest.approx(5400.00, abs=0.01)
        assert lot["provisional_kernel_lbs"] != lot["graded_kernel_weight_lbs"]

    def test_final_variant_reflects_actual_output_not_intake_estimate(self, api):
        """PRD (Routing Decisions and Hulling Runs): "This final, actual figure
        — not the intake estimate — is what grower payment is based on" and
        "The first completion moves the lot from `PROCESSING` to `PROCESSED`."

        Design: Difficulty/dual_variant_calc/kernel_weight_provisional_vs_final
        """
        _, lot = self._setup_full_lot(api)
        assert lot["status"] == "PROCESSED"
        # Final variant uses completed-run output only: 6000 * 0.90.
        assert lot["graded_kernel_weight_lbs"] == pytest.approx(5400.00, abs=0.01)
