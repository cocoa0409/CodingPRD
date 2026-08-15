"""Production run scheduling, sensing, settlement, and ledger boundaries
(PRD §2.8, §2.9, §2.10, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_reject_event,
    assert_kg,
    complete_run,
    create_approved_coil,
    create_assignment,
    create_die,
    create_press,
    create_production_run_payload,
    create_reject_event_payload,
    get_coil,
    get_die,
    get_order,
    get_press,
    get_run,
    install_die_on_press,
    schedule_run,
    setup_completed_run,
    setup_runnable,
    setup_running_run,
    start_run,
    validate_error,
    validate_success,
)


class TestRejectEvents:
    def test_reject_event_is_append_only_without_version(self, api, press_operator_headers):
        """PRD §2.4: "Three resource kinds are append-only ledger records and are deliberately exempt from the full common set: a `RejectEvent`, an `IndexPublication`, and a `PriceAdjustment` each carry only `id` and `created_at`. Neither `updated_at` nor `version` exists on these three, because they are never modified after creation."

        Design: Corner/entities/ppap_immutable_entity_has_no_version
        """
        ctx = setup_running_run()
        resp = api.create_reject_event(
            ctx["run"]["id"],
            create_reject_event_payload(station_number=2, sensor_code="MISFEED",
                                        quantity=3, sensed_at="2026-08-01T08:30:00Z"),
            press_operator_headers,
        )
        event = validate_success(resp, expected_status=201)
        assert "version" not in event, "RejectEvent must not carry version"
        assert "updated_at" not in event, "RejectEvent must not carry updated_at"
        assert event["id"], "system must populate id"
        assert event["created_at"], "system must populate created_at"

    def test_reject_counts_do_not_leak_across_runs(self, api):
        """PRD §3.7: "Each event belongs to exactly one run via its `production_run_id`, and the run's `reject_count` is always the sum of the `quantity` values of its own reject events — there is no cross-run leakage."
        PRD §3.7: "The run's `good_count` is its `shots_recorded` minus its total `reject_count`."

        Design: Corner/calculations/scrap_rate_uses_only_own_run_events
        """
        ctx = setup_runnable(quantity_ordered=500, coil_weight_kg=1000)
        run1 = schedule_run(ctx, "2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z")
        run2 = schedule_run(ctx, "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
        start_run(run1["id"])
        add_reject_event(run1["id"], quantity=5, station_number=1,
                         sensor_code="DOUBLE_BLANK", sensed_at="2026-08-01T08:15:00Z")
        complete_run(run1["id"], 50, ctx["coil"]["id"])

        start_run(run2["id"])
        complete_run(run2["id"], 40, ctx["coil"]["id"])
        run2_after = get_run(run2["id"])
        assert run2_after["reject_count"] == 0, (
            f"run1's 5 rejects must not leak into run2, got {run2_after['reject_count']}"
        )
        assert run2_after["good_count"] == 40


class TestCompletionGuards:
    def test_zero_shot_completion_rejected(self, api, press_operator_headers):
        """PRD §3.7: "The guards are: the run must be `RUNNING` (`ERR_INVALID_STATE`); a completion reporting zero shots is rejected with `ERR_NO_SHOTS_RECORDED` (422), because the run's actual scrap rate would be undefined; if the accumulated `reject_count` exceeds `shots_recorded` — which would make the good count negative — completion is rejected with `ERR_REJECT_COUNT_EXCEEDS_SHOTS` (422); a stale coil version is rejected with `ERR_STALE_VERSION` (412); and consumption that would push the coil's ledger below zero is rejected with `ERR_COIL_WEIGHT_EXCEEDED`."

        Design: Corner/calculations/run_completion_with_zero_shots_rejected
        """
        ctx = setup_running_run(quantity_ordered=500)
        coil = get_coil(ctx["coil"]["id"])
        resp = api.complete_production_run(
            ctx["run"]["id"],
            {"shots_recorded": 0, "expected_coil_version": coil["version"]},
            press_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_SHOTS_RECORDED)
        assert get_run(ctx["run"]["id"])["status"] == "RUNNING"

    def test_rejects_exceeding_shots_rejected(self, api, press_operator_headers):
        """PRD §3.7: "The guards are: the run must be `RUNNING` (`ERR_INVALID_STATE`); a completion reporting zero shots is rejected with `ERR_NO_SHOTS_RECORDED` (422), because the run's actual scrap rate would be undefined; if the accumulated `reject_count` exceeds `shots_recorded` — which would make the good count negative — completion is rejected with `ERR_REJECT_COUNT_EXCEEDS_SHOTS` (422); a stale coil version is rejected with `ERR_STALE_VERSION` (412); and consumption that would push the coil's ledger below zero is rejected with `ERR_COIL_WEIGHT_EXCEEDED`."

        Design: Corner/validations/rejects_exceeding_shots_rejected
        """
        ctx = setup_running_run(quantity_ordered=500)
        add_reject_event(ctx["run"]["id"], quantity=10, sensed_at="2026-08-01T08:10:00Z")
        coil = get_coil(ctx["coil"]["id"])
        resp = api.complete_production_run(
            ctx["run"]["id"],
            {"shots_recorded": 8, "expected_coil_version": coil["version"]},
            press_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REJECT_COUNT_EXCEEDS_SHOTS)
        assert get_run(ctx["run"]["id"])["status"] == "RUNNING"


class TestScrapAndSettlement:
    def test_reject_aggregation_and_good_count(self, api):
        """PRD §3.7: "Each event belongs to exactly one run via its `production_run_id`, and the run's `reject_count` is always the sum of the `quantity` values of its own reject events — there is no cross-run leakage."
        PRD §3.7: "The run's `good_count` is its `shots_recorded` minus its total `reject_count`."

        Design: Difficulty/dual_variant_calc/scrap_rate_engineering_standard_vs_sensed_actual
        """
        ctx = setup_running_run(quantity_ordered=500, coil_weight_kg=2000)
        add_reject_event(ctx["run"]["id"], quantity=140, station_number=3,
                         sensor_code="MISFEED", sensed_at="2026-08-01T10:00:00Z")
        add_reject_event(ctx["run"]["id"], quantity=120, station_number=5,
                         sensor_code="SLUG_DETECT", sensed_at="2026-08-01T11:00:00Z")
        complete_run(ctx["run"]["id"], 800, ctx["coil"]["id"])
        run_after = get_run(ctx["run"]["id"])
        assert run_after["reject_count"] == 260
        assert run_after["good_count"] == 540, (
            f"good_count must be 800 - 260 = 540, got {run_after['good_count']}"
        )

    def test_settlement_decrements_coil_by_good_parts_times_steel_content(self, api):
        """PRD §3.7: "Its `steel_consumed_kg` is the `good_count` multiplied by the part's `steel_content_kg`, rounded to 3 decimal places half up. The coil's `remaining_weight_kg` is decremented by exactly that amount at the same precision, the coil's `version` increments, and if the remainder is exactly zero the coil moves `APPROVED` to `DEPLETED`."

        Design: Difficulty/dual_variant_calc/scrap_rate_engineering_standard_vs_sensed_actual
        """
        # 540 good parts at 0.85 kg steel content consume 459.000 kg of a 2000 kg coil.
        ctx = setup_running_run(quantity_ordered=500, coil_weight_kg=2000)
        add_reject_event(ctx["run"]["id"], quantity=140, station_number=3,
                         sensor_code="MISFEED", sensed_at="2026-08-01T10:00:00Z")
        add_reject_event(ctx["run"]["id"], quantity=120, station_number=5,
                         sensor_code="SLUG_DETECT", sensed_at="2026-08-01T11:00:00Z")
        complete_run(ctx["run"]["id"], 800, ctx["coil"]["id"])
        coil_after = get_coil(ctx["coil"]["id"])
        assert_kg(coil_after["remaining_weight_kg"], 1541.0, "remaining_weight_kg")
        assert coil_after["status"] == "APPROVED"

    def test_exact_zero_remainder_depletes_coil(self, api):
        """PRD §2.9: "The ledger never goes negative — a completion that would drive it below zero is rejected with `ERR_COIL_WEIGHT_EXCEEDED` — and when a completion lands it on exactly zero, the coil transitions itself from `APPROVED` to `DEPLETED`."

        Design: Difficulty/transitive_cascade/run_completion_ledger_cascade_depth2
        """
        # 100 good parts at 0.85 kg consume exactly the coil's 85.000 kg.
        ctx = setup_completed_run(shots_recorded=100, quantity_ordered=100,
                                  coil_weight_kg=85.0)
        coil_after = ctx["coil_after"]
        assert_kg(coil_after["remaining_weight_kg"], 0.0, "remaining_weight_kg")
        assert coil_after["status"] == "DEPLETED", (
            "remainder landing on exactly zero must auto-transition APPROVED -> DEPLETED"
        )

    def test_run_records_exact_steel_consumed(self, api):
        """PRD §3.7: "Its `steel_consumed_kg` is the `good_count` multiplied by the part's `steel_content_kg`, rounded to 3 decimal places half up. The coil's `remaining_weight_kg` is decremented by exactly that amount at the same precision, the coil's `version` increments, and if the remainder is exactly zero the coil moves `APPROVED` to `DEPLETED`."

        Design: Difficulty/transitive_cascade/run_completion_ledger_cascade_depth2
        """
        ctx = setup_completed_run(shots_recorded=100, quantity_ordered=100,
                                  coil_weight_kg=85.0)
        run_after = get_run(ctx["run"]["id"])
        assert run_after["status"] == "COMPLETED"
        assert_kg(run_after["steel_consumed_kg"], 85.0, "steel_consumed_kg")


class TestCoilDepletionBoundary:
    def test_remainder_exactly_zero_transitions_to_depleted(self, api):
        """PRD §2.9: "The ledger never goes negative — a completion that would drive it below zero is rejected with `ERR_COIL_WEIGHT_EXCEEDED` — and when a completion lands it on exactly zero, the coil transitions itself from `APPROVED` to `DEPLETED`."

        Design: Difficulty/boundary_precision_check/coil_depletion_at_exact_zero
        """
        ctx = setup_completed_run(shots_recorded=100, quantity_ordered=100,
                                  coil_weight_kg=85.0, heat_lot_number="HL-K")
        assert_kg(ctx["coil_after"]["remaining_weight_kg"], 0.0)
        assert ctx["coil_after"]["status"] == "DEPLETED"

    def test_remainder_one_milligram_above_zero_stays_approved(self, api):
        """PRD §2.9: "The ledger never goes negative — a completion that would drive it below zero is rejected with `ERR_COIL_WEIGHT_EXCEEDED` — and when a completion lands it on exactly zero, the coil transitions itself from `APPROVED` to `DEPLETED`."

        Design: Difficulty/boundary_precision_check/coil_depletion_at_exact_zero
        """
        ctx = setup_completed_run(shots_recorded=100, quantity_ordered=100,
                                  coil_weight_kg=85.001, heat_lot_number="HL-K")
        assert_kg(ctx["coil_after"]["remaining_weight_kg"], 0.001)
        assert ctx["coil_after"]["status"] == "APPROVED", (
            "0.001 kg remaining is above the exactly-zero boundary and must not deplete"
        )


class TestRunWindowOverlap:
    def test_back_to_back_run_window_allowed(self, api, production_planner_headers):
        """PRD §2.10: "For production runs, the window from `scheduled_start` to `scheduled_end` is treated as half-open: a new run's window must not overlap any existing `SCHEDULED` or `RUNNING` run on the same press, though back-to-back scheduling — one run's `scheduled_start` exactly equal to the previous run's `scheduled_end` — is allowed. A violation is rejected with `ERR_PRESS_SCHEDULE_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/run_window_half_open_overlap
        """
        ctx = setup_runnable(quantity_ordered=100, coil_weight_kg=2000)
        schedule_run(ctx, "2026-08-01T08:00:00Z", "2026-08-01T12:00:00Z")
        resp = api.create_production_run(
            create_production_run_payload(
                ctx["order"]["id"], ctx["press"]["id"], ctx["die"]["id"], ctx["coil"]["id"],
                scheduled_start="2026-08-01T12:00:00Z",
                scheduled_end="2026-08-01T16:00:00Z",
            ),
            production_planner_headers,
        )
        adjacent = validate_success(resp, expected_status=201)
        assert adjacent["status"] == "SCHEDULED", (
            "half-open windows: a start exactly equal to the prior end is allowed"
        )

    def test_one_second_overlap_rejected(self, api, production_planner_headers):
        """PRD §2.10: "For production runs, the window from `scheduled_start` to `scheduled_end` is treated as half-open: a new run's window must not overlap any existing `SCHEDULED` or `RUNNING` run on the same press, though back-to-back scheduling — one run's `scheduled_start` exactly equal to the previous run's `scheduled_end` — is allowed. A violation is rejected with `ERR_PRESS_SCHEDULE_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/run_window_half_open_overlap
        """
        ctx = setup_runnable(quantity_ordered=100, coil_weight_kg=2000)
        schedule_run(ctx, "2026-08-01T08:00:00Z", "2026-08-01T12:00:00Z")
        resp = api.create_production_run(
            create_production_run_payload(
                ctx["order"]["id"], ctx["press"]["id"], ctx["die"]["id"], ctx["coil"]["id"],
                scheduled_start="2026-08-01T11:59:59Z",
                scheduled_end="2026-08-01T13:00:00Z",
            ),
            production_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PRESS_SCHEDULE_CONFLICT)


class TestMaterialVsSchedulePriority:
    def _setup_with_bad_coil(self):
        """Released order, press, installed die, one SCHEDULED run 08:00-12:00 on a
        matching coil, plus an approved coil of the wrong material spec."""
        ctx = setup_runnable(quantity_ordered=10, coil_weight_kg=1000)
        ctx["run1"] = schedule_run(ctx, "2026-08-01T08:00:00Z", "2026-08-01T12:00:00Z")
        ctx["coil_bad"] = create_approved_coil(
            material_spec="DP600", thickness_mm=1.2, received_weight_kg=1000
        )
        return ctx

    def test_material_mismatch_beats_window_conflict(self, api, production_planner_headers):
        """PRD §2.5: "When several checks could reject the same request, the server evaluates them in a single, fixed pipeline order, and the first failing check determines the response."
        PRD §2.5: "8. **Material compatibility.** The coil's `material_spec` equals the part's `material_spec` and the coil's `thickness_mm` equals the part's `thickness_mm`, checked when a run is scheduled and again when it is started. Failure: `ERR_MATERIAL_MISMATCH` (422)."
        PRD §2.5: "9. **Run-window overlap.** A new run's half-open window must not overlap another `SCHEDULED` or `RUNNING` run on the same press (§2.10). Failure: `ERR_PRESS_SCHEDULE_CONFLICT` (409)."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_temporal_on_run_create
        """
        ctx = self._setup_with_bad_coil()
        # Wrong material AND an overlapping window: check 8 fires before check 9.
        resp = api.create_production_run(
            create_production_run_payload(
                ctx["order"]["id"], ctx["press"]["id"], ctx["die"]["id"],
                ctx["coil_bad"]["id"],
                scheduled_start="2026-08-01T10:00:00Z",
                scheduled_end="2026-08-01T14:00:00Z",
            ),
            production_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MATERIAL_MISMATCH)

    def test_window_conflict_fires_when_material_matches(self, api, production_planner_headers):
        """PRD §2.5: "When several checks could reject the same request, the server evaluates them in a single, fixed pipeline order, and the first failing check determines the response."
        PRD §2.5: "9. **Run-window overlap.** A new run's half-open window must not overlap another `SCHEDULED` or `RUNNING` run on the same press (§2.10). Failure: `ERR_PRESS_SCHEDULE_CONFLICT` (409)."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_temporal_on_run_create
        """
        ctx = self._setup_with_bad_coil()
        # Matching material, same overlapping window: check 8 passes, check 9 fires.
        resp = api.create_production_run(
            create_production_run_payload(
                ctx["order"]["id"], ctx["press"]["id"], ctx["die"]["id"],
                ctx["coil"]["id"],
                scheduled_start="2026-08-01T10:00:00Z",
                scheduled_end="2026-08-01T14:00:00Z",
            ),
            production_planner_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PRESS_SCHEDULE_CONFLICT)


class TestCoilLedgerOcc:
    def test_stale_coil_version_rejected_at_run_completion(self, api, press_operator_headers):
        """PRD §2.8: "Completing a production run requires `expected_coil_version`, matched against the coil's current `version`. This guards the conserved coil ledger: if another writer has just completed a different run on the same coil — which legitimately decremented `remaining_weight_kg` and advanced the coil's version — the completing run's consumption decision rests on a stale view of the ledger and is rejected. The completing run's own state is validly `RUNNING`; only the coil version check rejects the write."

        Design: Corner/errors/err_stale_version_run_complete
        """
        # Two RUNNING runs on different presses/dies share one coil.
        ctx = setup_runnable(quantity_ordered=500, coil_weight_kg=1000)
        die_b = create_die(rated_tonnage=300, min_bed_width_mm=1800)
        create_assignment(ctx["part"]["id"], die_b["id"])
        press_b = create_press()
        install_die_on_press(press_b["id"], die_b["id"])
        run1 = schedule_run(ctx, "2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z")
        run2 = schedule_run(ctx, "2026-08-01T08:00:00Z", "2026-08-01T09:00:00Z",
                            press_id=press_b["id"], die_id=die_b["id"])
        start_run(run1["id"])
        start_run(run2["id"])

        stale_version = get_coil(ctx["coil"]["id"])["version"]
        complete_run(run1["id"], 50, ctx["coil"]["id"])  # advances the coil version
        resp = api.complete_production_run(
            run2["id"],
            {"shots_recorded": 40, "expected_coil_version": stale_version},
            press_operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_run(run2["id"])["status"] == "RUNNING", (
            "the rejected completion must leave the validly RUNNING run untouched"
        )
        coil_after = get_coil(ctx["coil"]["id"])
        assert_kg(coil_after["remaining_weight_kg"], 957.5,
                  "only run1's 42.5 kg consumption may be applied")


class TestImmediateConsistency:
    def test_run_completion_side_effects_visible_immediately(self, api):
        """PRD §3.7: "On success the books settle in one motion. The run's `good_count` is its `shots_recorded` minus its total `reject_count`. Its `steel_consumed_kg` is the `good_count` multiplied by the part's `steel_content_kg`, rounded to 3 decimal places half up. The coil's `remaining_weight_kg` is decremented by exactly that amount at the same precision, the coil's `version` increments, and if the remainder is exactly zero the coil moves `APPROVED` to `DEPLETED`. The press returns to `IDLE`. The order's `quantity_produced_good` increases by the `good_count` and its `quantity_scrapped` increases by the `reject_count`. The die ages: both `total_shots_lifetime` and `shots_since_repair` increase by the run's `shots_recorded`."

        Design: Corner/consistency_model/immediate_consistency_run_completion_visible
        """
        ctx = setup_completed_run(shots_recorded=100, quantity_ordered=100,
                                  coil_weight_kg=200)
        coil_after = get_coil(ctx["coil"]["id"])
        assert_kg(coil_after["remaining_weight_kg"], 115.0, "coil remainder visible now")

        order_after = get_order(ctx["order"]["id"])
        assert order_after["quantity_produced_good"] == 100
        assert order_after["quantity_scrapped"] == 0

        die_after = get_die(ctx["die"]["id"])
        assert die_after["total_shots_lifetime"] == 100
        assert die_after["shots_since_repair"] == 100

        press_after = get_press(ctx["press"]["id"])
        assert press_after["status"] == "IDLE"
