"""Fryer oil management: TPM accrual, dilution, movements, the quality-hold
cascade, immutable movement records, and oil-side OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_line,
    create_line_payload,
    create_oil_movement_payload,
    get_line_fryer_oil,
    get_success_data,
    make_line_operator_headers,
    make_quality_tech_headers,
    record_weight_check,
    record_weight_checks,
    schedule_run,
    set_clock,
    setup_running_run,
    setup_system_held_run,
    start_run,
    validate_error,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
OP = TEST_USERS["line_operator_headers"]


class TestTpmDilutionWithTempFactor:
    def _setup_dilution_scenario(self, api):
        """Run started; check 1 fries 4000 lbs at target; TOP_OFF 6 gal."""
        ctx = setup_running_run(lbs_planned=8000, cases_planned=400,
                                start="2026-08-02T08:00:00Z",
                                end="2026-08-02T10:00:00Z")
        record_weight_check(ctx["run"]["id"], bag_weight_g=100.2,
                            lbs_fried_since_last_check=4000, avg_fry_temp_c=180.0)
        oil = get_line_fryer_oil(ctx["line"]["id"])
        get_success_data(api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], oil["version"], movement_type="TOP_OFF",
                gallons=6, unit_price_cents_per_gal=700), OP))
        return ctx, oil["id"]

    def test_dilution_then_hot_interval_composition(self, api):
        """PRD §3.4: "For every frying-accrual event of L pounds — each
        sample's `lbs_fried_since_last_check`, and later the residual pounds
        computed at completion — the oil's `tpm_pct` increases by 2.0 points
        per thousand pounds fried, scaled by a temperature factor: the factor
        is 1.5 when the interval's `avg_fry_temp_c` deviates from the product's
        `fry_target_temp_c` by more than 5.0 degrees Celsius, and 1.0 when the
        deviation is 5.0 degrees or less (a deviation of exactly 5.0 degrees
        yields the factor 1.0)."
        PRD §3.4: "A `TOP_OFF` of g gallons dilutes: the `tpm_pct` is
        multiplied by the ratio of the pre-top-off `current_gallons` to the
        post-top-off volume, then `current_gallons` increases by g"

        Design: Difficulty/combinatorial_formula/tpm_dilution_with_temp_factor_composition
        """
        ctx, oil_id = self._setup_dilution_scenario(api)
        # 4000 lbs at 186.0 C: deviation 6.0 > 5.0 -> factor 1.5
        record_weight_check(ctx["run"]["id"], bag_weight_g=100.2,
                            lbs_fried_since_last_check=4000, avg_fry_temp_c=186.0)
        oil = get_success_data(api.get_fryer_oil(oil_id, PM))
        # 8.5 diluted to 8.5*94/100 = 7.99, then + (4 * 2.0 * 1.5) = 19.99
        assert oil["tpm_pct"] == pytest.approx(19.99)
        assert oil["current_gallons"] == pytest.approx(94)
        assert oil["state"] == "ACTIVE", "19.99 is below the 27.0 threshold"

    def test_intermediate_accrual_and_dilution_values(self, api):
        """PRD §3.4: "A `TOP_OFF` of g gallons dilutes: the `tpm_pct` is
        multiplied by the ratio of the pre-top-off `current_gallons` to the
        post-top-off volume, then `current_gallons` increases by g"
        PRD §3.4: "at start, `locked_oil_price_cents_per_gal` is set to the oil
        record's `last_oil_price_cents_per_gal` — the
        `unit_price_cents_per_gal` of the most recent priced movement (a
        top-off or full replacement), ordered by `recorded_at` with ties broken
        by `created_at`"

        Design: Difficulty/combinatorial_formula/tpm_dilution_with_temp_factor_composition
        """
        ctx = setup_running_run(lbs_planned=8000, cases_planned=400,
                                start="2026-08-02T08:00:00Z",
                                end="2026-08-02T10:00:00Z")
        record_weight_check(ctx["run"]["id"], bag_weight_g=100.2,
                            lbs_fried_since_last_check=4000, avg_fry_temp_c=180.0)
        oil = get_line_fryer_oil(ctx["line"]["id"])
        # 0.5 + (4000/1000) * 2.0 * 1.0 = 8.5; absorbed 6.000 gal -> 94
        assert oil["tpm_pct"] == pytest.approx(8.5)
        assert oil["current_gallons"] == pytest.approx(94)
        movement = get_success_data(api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], oil["version"], movement_type="TOP_OFF",
                gallons=6, unit_price_cents_per_gal=700), OP))
        assert movement["tpm_after_pct"] == pytest.approx(7.99)
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        assert oil["current_gallons"] == pytest.approx(100)
        assert oil["tpm_pct"] == pytest.approx(7.99)
        assert oil["last_oil_price_cents_per_gal"] == 700


class TestTopOffDiscardConservation:
    def _setup_after_accrual(self, api):
        ctx = setup_running_run(lbs_planned=4000, cases_planned=200,
                                start="2026-08-02T08:00:00Z",
                                end="2026-08-02T10:00:00Z")
        record_weight_check(ctx["run"]["id"], bag_weight_g=100.1,
                            lbs_fried_since_last_check=4000, avg_fry_temp_c=180.0)
        return ctx, get_line_fryer_oil(ctx["line"]["id"])

    def test_topoff_restores_volume_and_dilutes(self, api):
        """PRD §2.10: "It equals the `initial_charge_gallons` plus the gallons
        of every top-off and every full replacement, minus the gallons of every
        discard, minus the absorbed volume — where the absorbed volume is the
        `total_lbs_since_replace` multiplied by one and a half gallons per
        thousand pounds, rounded half-up to three decimals."
        PRD §3.4: "A `TOP_OFF` of g gallons dilutes: the `tpm_pct` is
        multiplied by the ratio of the pre-top-off `current_gallons` to the
        post-top-off volume, then `current_gallons` increases by g"

        Design: Difficulty/compensating_invariant/oil_gallons_topoff_discard_conservation
        """
        ctx, oil = self._setup_after_accrual(api)
        get_success_data(api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], oil["version"], movement_type="TOP_OFF",
                gallons=6, unit_price_cents_per_gal=600), OP))
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        # 94 + 6 = 100; concentration diluted 8.5 * 94/100 = 7.99
        assert oil["current_gallons"] == pytest.approx(100)
        assert oil["tpm_pct"] == pytest.approx(7.99)

    def test_compensating_discard_restores_mass_balance(self, api):
        """PRD §2.10: "It equals the `initial_charge_gallons` plus the gallons
        of every top-off and every full replacement, minus the gallons of every
        discard, minus the absorbed volume"
        PRD §3.4: "A `DISCARD` of g gallons leaves `tpm_pct` unchanged and
        decreases `current_gallons` by g"

        Design: Difficulty/compensating_invariant/oil_gallons_topoff_discard_conservation
        """
        ctx, oil = self._setup_after_accrual(api)
        get_success_data(api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], oil["version"], movement_type="TOP_OFF",
                gallons=6, unit_price_cents_per_gal=600), OP))
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        get_success_data(api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], oil["version"], movement_type="DISCARD",
                gallons=6, unit_price_cents_per_gal=None), OP))
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        # 100 + 6 - 6 - 6.000 absorbed = 94: the forward/compensating pair
        # restores the mass balance exactly
        assert oil["current_gallons"] == pytest.approx(94)
        # dilution is one-way: the invariant covers gallons, not concentration
        assert oil["tpm_pct"] == pytest.approx(7.99)


class TestTpmThresholdBoundary:
    def test_below_threshold_then_exact_crossing(self, api):
        """PRD §3.4: "After every such recomputation — movements included —
        the oil's lifecycle state is re-evaluated: oil whose `tpm_pct` reaches
        or exceeds 27.0 moves from `ACTIVE` to `QUALITY_HOLD`"
        PRD §3.4: "When oil crosses the threshold while a run is `RUNNING` on
        the line, that run is forced from `RUNNING` to `HELD` with
        `hold_placed_by_user_id` set to null — a system hold."

        Design: Difficulty/boundary_precision_check/tpm_threshold_27_inclusive_boundary
        """
        ctx = setup_running_run(lbs_planned=20000, cases_planned=1000,
                                start="2026-08-02T08:00:00Z",
                                end="2026-08-02T16:00:00Z")
        run_id = ctx["run"]["id"]
        record_weight_checks(run_id, [(100.1, 5000, 180.0),
                                      (100.1, 5000, 180.0),
                                      (100.1, 3245, 180.0)])
        oil = get_line_fryer_oil(ctx["line"]["id"])
        # 0.5 + 13.245 * 2.0 = 26.99: strictly below, still ACTIVE
        assert oil["tpm_pct"] == pytest.approx(26.99)
        assert oil["state"] == "ACTIVE"
        # +5 lbs -> 13,250 lbs -> exactly 27.0: the inclusive boundary fires
        record_weight_check(run_id, bag_weight_g=100.1,
                            lbs_fried_since_last_check=5, avg_fry_temp_c=180.0)
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        assert oil["tpm_pct"] == pytest.approx(27.0)
        assert oil["state"] == "QUALITY_HOLD"
        run = get_success_data(api.get_run(run_id, PM))
        assert run["execution_status"] == "HELD"
        assert run["hold_placed_by_user_id"] is None

    def test_just_below_threshold_keeps_oil_active(self, api):
        """PRD §3.4: "oil whose `tpm_pct` reaches or exceeds 27.0 moves from
        `ACTIVE` to `QUALITY_HOLD`; oil whose recomputed `tpm_pct` falls back
        below 27.0 returns from `QUALITY_HOLD` to `ACTIVE`."

        Design: Difficulty/boundary_precision_check/tpm_threshold_27_inclusive_boundary
        """
        ctx = setup_running_run(lbs_planned=20000, cases_planned=1000,
                                start="2026-08-02T08:00:00Z",
                                end="2026-08-02T16:00:00Z")
        run_id = ctx["run"]["id"]
        record_weight_checks(run_id, [(100.1, 5000, 180.0),
                                      (100.1, 5000, 180.0),
                                      (100.1, 3245, 180.0)])
        oil = get_line_fryer_oil(ctx["line"]["id"])
        assert oil["tpm_pct"] == pytest.approx(26.99)
        assert oil["state"] == "ACTIVE"
        # +2 lbs -> 13,247 lbs -> 0.5 + 26.494 = 26.994, stored as 26.99:
        # still below the inclusive threshold
        record_weight_check(run_id, bag_weight_g=100.1,
                            lbs_fried_since_last_check=2, avg_fry_temp_c=180.0)
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        assert oil["tpm_pct"] == pytest.approx(26.99)
        assert oil["state"] == "ACTIVE"
        run = get_success_data(api.get_run(run_id, PM))
        assert run["execution_status"] == "RUNNING"


class TestHoldFiltrationCycle:
    def test_tpm_breach_holds_oil_and_run_with_system_holder(self, api):
        """PRD §3.4: "When oil crosses the threshold while a run is `RUNNING`
        on the line, that run is forced from `RUNNING` to `HELD` with
        `hold_placed_by_user_id` set to null — a system hold."

        Design: Difficulty/non_linear_state_machine/fryer_oil_hold_filtration_cycle
        """
        ctx = setup_system_held_run()
        assert ctx["oil"]["tpm_pct"] == pytest.approx(27.0)
        assert ctx["oil"]["state"] == "QUALITY_HOLD"
        assert ctx["run"]["execution_status"] == "HELD"
        assert ctx["run"]["hold_placed_by_user_id"] is None

    def test_filtration_restores_active_but_run_stays_held(self, api):
        """PRD §3.4: "A `FILTRATION` multiplies `tpm_pct` by 0.6 without
        changing the volume."
        PRD §3.4: "Recovery is asymmetric by design: filtration or replacement
        may return the oil to `ACTIVE`, but releasing the held run is never
        automatic — a `QualityTechnician` must still release the hold
        explicitly."

        Design: Difficulty/non_linear_state_machine/fryer_oil_hold_filtration_cycle
        """
        ctx = setup_system_held_run()
        oil = ctx["oil"]
        get_success_data(api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], oil["version"], movement_type="FILTRATION",
                gallons=0, unit_price_cents_per_gal=None), OP))
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        # 27.0 * 0.6 = 16.2 -> back below the threshold
        assert oil["tpm_pct"] == pytest.approx(16.2)
        assert oil["state"] == "ACTIVE"
        run = get_success_data(api.get_run(ctx["run"]["id"], PM))
        assert run["execution_status"] == "HELD", "no automatic release"
        assert run["hold_placed_by_user_id"] is None


class TestOilMovementContract:
    def test_oil_movement_immutable_event_record(self, api):
        """PRD §2.5: "An OilMovement and a WeightCheck are immutable
        point-in-time records: each carries only `id` and `created_at` from the
        common set; both `updated_at` and `version` are absent from them."
        PRD §3.4: "A `DISCARD` of g gallons leaves `tpm_pct` unchanged and
        decreases `current_gallons` by g"

        Design: Corner/entities/oil_movement_immutable_event_record
        """
        line = create_line()
        oil = get_line_fryer_oil(line["id"])
        movement = get_success_data(api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], oil["version"], movement_type="DISCARD",
                gallons=5, unit_price_cents_per_gal=None), OP))
        movement = get_success_data(api.get_oil_movement(movement["id"], PM))
        assert "version" not in movement and "updated_at" not in movement
        assert movement["tpm_after_pct"] == pytest.approx(0.5)
        assert movement["gallons"] == 5
        assert isinstance(movement["recorded_by_user_id"], str)

    def test_oil_topoff_overflow_rejected(self, api):
        """PRD §3.4: "a top-off that would push `current_gallons` above the
        line's `oil_capacity_gallons` is rejected with `ERR_OIL_OVERFLOW`."

        Design: Corner/validations/oil_topoff_overflow_rejected
        """
        line = create_line()
        oil = get_line_fryer_oil(line["id"])
        assert oil["current_gallons"] == 100  # sump starts full
        resp = api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], oil["version"], movement_type="TOP_OFF",
                gallons=1, unit_price_cents_per_gal=600), OP)
        validate_error(resp, ApiErrorId.ERR_OIL_OVERFLOW, 422)
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        assert oil["current_gallons"] == 100, "a rejected movement records nothing"

    def test_oil_discard_underflow_rejected(self, api):
        """PRD §3.4: "discarding more than the current volume is rejected with
        `ERR_INSUFFICIENT_OIL`, while discarding exactly the entire current
        volume constitutes a full drain and moves the oil from `ACTIVE` (or
        `QUALITY_HOLD`) to `DRAINING`."

        Design: Corner/validations/oil_discard_underflow_rejected
        """
        line = create_line()
        oil = get_line_fryer_oil(line["id"])
        resp = api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], oil["version"], movement_type="DISCARD",
                gallons=101, unit_price_cents_per_gal=None), OP)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_OIL, 422)
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        # discarding exactly the full volume is a legal full drain
        get_success_data(api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], oil["version"], movement_type="DISCARD",
                gallons=100, unit_price_cents_per_gal=None), OP))
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        assert oil["state"] == "DRAINING"
        assert oil["current_gallons"] == 0

    def test_temp_factor_boundary_exactly_five_degrees(self, api):
        """PRD §3.4: "the factor is 1.5 when the interval's `avg_fry_temp_c`
        deviates from the product's `fry_target_temp_c` by more than 5.0
        degrees Celsius, and 1.0 when the deviation is 5.0 degrees or less (a
        deviation of exactly 5.0 degrees yields the factor 1.0)."

        Design: Corner/calculations/temp_factor_boundary_exactly_five_degrees
        """
        ctx = setup_running_run(lbs_planned=1000, cases_planned=50)
        record_weight_check(ctx["run"]["id"], bag_weight_g=100.1,
                            lbs_fried_since_last_check=1000, avg_fry_temp_c=185.0)
        oil = get_line_fryer_oil(ctx["line"]["id"])
        # deviation exactly 5.0 -> factor 1.0: 0.5 + 1.0 * 2.0 * 1.0 = 2.5
        assert oil["tpm_pct"] == pytest.approx(2.5)
        assert oil["state"] == "ACTIVE"


class TestOilMovementOcc:
    def test_occ_oil_movement_stale_version(self, api):
        """PRD §2.7: "operators compute replenishment and discard volumes from
        the TPM and gallons baseline they read, so if any earlier movement or
        frying accrual has advanced the oil record's version, the movement is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_oil_movement_stale_version
        """
        line = create_line()
        oil = get_line_fryer_oil(line["id"])
        observed_v = oil["version"]
        get_success_data(api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], observed_v, movement_type="DISCARD",
                gallons=10, unit_price_cents_per_gal=None), OP))
        # the first movement advanced the oil's version; the baseline the
        # operator read is now stale
        resp = api.create_oil_movement(
            create_oil_movement_payload(
                oil["id"], observed_v, movement_type="DISCARD",
                gallons=5, unit_price_cents_per_gal=None), OP)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        oil = get_success_data(api.get_fryer_oil(oil["id"], PM))
        assert oil["current_gallons"] == pytest.approx(90), (
            "the stale write must be rejected cleanly"
        )


class TestHoldReleaseOilGate:
    def test_release_hold_blocked_while_oil_on_hold(self, api):
        """PRD §3.4: "Releasing a hold is exclusively a `QualityTechnician`
        action: the run must be `HELD`, the line's oil must be `ACTIVE`
        (otherwise `ERR_OIL_QUALITY_HOLD`)"

        Design: Corner/validations/release_hold_blocked_while_oil_on_hold
        """
        ctx = setup_system_held_run()
        assert ctx["oil"]["state"] == "QUALITY_HOLD"
        resp = api.release_hold(ctx["run"]["id"], make_quality_tech_headers("qt-1"))
        validate_error(resp, ApiErrorId.ERR_OIL_QUALITY_HOLD, 422)
        run = get_success_data(api.get_run(ctx["run"]["id"], PM))
        assert run["execution_status"] == "HELD"
