"""Dryer runs: scheduling conflicts, start/complete/abort lifecycle, metered
vs estimated energy pass-through, and shrink reconciliation (PRD §3.5, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_dryer_run,
    capacity_calendar,
    complete_run,
    create_dried_lot,
    create_dryer_run_payload,
    create_queued_lot,
    create_tested_lot,
    get_lot,
    get_run,
    get_ticket,
    make_operator_headers,
    schedule_run,
    set_clock,
    setup_base,
    setup_dried_lot_scenario,
    start_run,
    validate_error,
    validate_success,
)


class TestRunCompletionGate:
    def test_run_complete_from_scheduled_rejected(self, api, operator_headers):
        """PRD §2.9: "State permission — the target resource must be in a state
        permitting the operation" and "Other state mismatches yield
        `ERR_INVALID_STATE` (all HTTP 409)."
        PRD §3.5: "An `IN_PROGRESS` run that cannot finish may be aborted —
        `IN_PROGRESS` → `ABORTED`, terminal."

        Design: Corner/state_machines/run_complete_from_scheduled_rejected
        """
        ctx = setup_base()
        lot, _t, ticket = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-05",
            requested_bushels=200, sample_moisture_pct=20.0)
        run = schedule_run(ctx["unit"]["id"], lot["id"], ticket["id"])
        res = api.complete_dryer_run(
            run["id"],
            {"scale_out_weight_lbs": 9050, "discharge_moisture_pct": 15.0,
             "meter_end_therms": 1265.0},
            operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = get_run(run["id"])
        assert after["status"] == "SCHEDULED"
        assert after.get("energy_charge_cents") is None


class TestRunAbortCompensation:
    def test_run_abort_compensation_restores_ticket_and_lot(self, api, manager_headers):
        """PRD §3.5: "Abortion is a compensation pair: the consumed ticket
        returns `CONSUMED` → `CONFIRMED` so its capacity is committed again, and
        the lot returns `DRYING` → `QUEUED`, ready to be rescheduled."
        PRD §3.4: "Committed bushels are the sum of `requested_bushels` over the
        unit-date's `CONFIRMED` tickets; a ticket `CONSUMED` by an executing run
        still occupies its day, while `PENDING`, `PREEMPTED`, `CANCELLED`, and
        `EXPIRED` tickets hold nothing."

        Design: Corner/state_machines/run_abort_compensation_restores_ticket_and_lot
        """
        ctx = setup_base()
        lot, _t, ticket = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-05",
            requested_bushels=200, sample_moisture_pct=20.0)
        run = schedule_run(ctx["unit"]["id"], lot["id"], ticket["id"])
        set_clock("2026-09-05T08:00:00Z")
        start_run(run["id"], meter_start_therms=1200.0)
        # CONSUMED still occupies its day while the run executes.
        assert capacity_calendar(ctx["unit"]["id"], "2026-09-05")[
            "total_committed_bushels"] == 200

        aborted = validate_success(
            api.abort_dryer_run(run["id"], make_operator_headers("op-1")), 200)
        assert aborted["status"] == "ABORTED"
        assert get_ticket(ticket["id"])["status"] == "CONFIRMED"
        assert get_lot(lot["id"])["status"] == "QUEUED"
        assert capacity_calendar(ctx["unit"]["id"], "2026-09-05")[
            "total_committed_bushels"] == 200


class TestMeterReadingValidation:
    def test_meter_reading_not_advanced_rejected(self, api, operator_headers):
        """PRD §3.5: "By default — `energy_estimated` false — the operator
        supplies the closing `meter_end_therms`, which must be strictly greater
        than `meter_start_therms` or the completion is rejected with
        `ERR_METER_READING_INVALID` (HTTP 422); the run's `fuel_therms` is then
        the meter delta."

        Design: Corner/validations/meter_reading_not_advanced_rejected
        """
        ctx = setup_base()
        lot, _t, ticket = create_queued_lot(
            ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-05",
            requested_bushels=200, sample_moisture_pct=20.0)
        run = schedule_run(ctx["unit"]["id"], lot["id"], ticket["id"])
        set_clock("2026-09-05T08:00:00Z")
        start_run(run["id"], meter_start_therms=1200.0)
        set_clock("2026-09-05T12:00:00Z")
        res = api.complete_dryer_run(
            run["id"],
            {"scale_out_weight_lbs": 9050, "discharge_moisture_pct": 15.0,
             "meter_end_therms": 1200.0},
            operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_METER_READING_INVALID, expected_status=422)
        assert get_run(run["id"])["status"] == "IN_PROGRESS"


class TestCooldownBuffer:
    """Half-open run windows plus a 30-minute cooldown treated as occupied."""

    def _three_queued_lots(self):
        ctx = setup_base()
        lots = []
        for _ in range(3):
            lot, _t, ticket = create_queued_lot(
                ctx["cust"]["id"], ctx["unit"]["id"], window_date="2026-09-05",
                requested_bushels=300, sample_moisture_pct=20.0)
            lots.append((lot, ticket))
        return ctx, lots

    def test_run_starting_exactly_at_end_plus_cooldown_legal(self, api, operator_headers):
        """PRD §3.5: "Scheduled windows are half-open — a run occupying its
        window does not conflict with another beginning exactly when it ends —
        and the unit's `cooldown_minutes` idle gap is treated as occupied time
        around each run, so a new window that collides with another non-cancelled
        run on the same unit, cooldown buffer included, is rejected with
        `ERR_RUN_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/dryer_run_cooldown_buffer_halfopen
        """
        ctx, lots = self._three_queued_lots()
        r1 = schedule_run(ctx["unit"]["id"], lots[0][0]["id"], lots[0][1]["id"],
                          scheduled_start="2026-09-05T08:00:00Z",
                          scheduled_end="2026-09-05T12:00:00Z")
        assert_dryer_run(r1)
        # R1's buffered tail ends at 12:30; R2 begins exactly then — legal.
        res = api.create_dryer_run(
            create_dryer_run_payload(
                ctx["unit"]["id"], lots[1][0]["id"], lots[1][1]["id"],
                scheduled_start="2026-09-05T12:30:00Z",
                scheduled_end="2026-09-05T16:00:00Z"),
            operator_headers,
        )
        assert validate_success(res, 201)["status"] == "SCHEDULED"

    def test_run_inside_buffered_tail_rejected(self, api, operator_headers):
        """PRD §3.5: "Scheduled windows are half-open — a run occupying its
        window does not conflict with another beginning exactly when it ends —
        and the unit's `cooldown_minutes` idle gap is treated as occupied time
        around each run, so a new window that collides with another non-cancelled
        run on the same unit, cooldown buffer included, is rejected with
        `ERR_RUN_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/dryer_run_cooldown_buffer_halfopen
        """
        ctx, lots = self._three_queued_lots()
        schedule_run(ctx["unit"]["id"], lots[0][0]["id"], lots[0][1]["id"],
                     scheduled_start="2026-09-05T08:00:00Z",
                     scheduled_end="2026-09-05T12:00:00Z")
        # 12:00 lies inside R1's buffered tail [12:00, 12:30) — collision.
        res = api.create_dryer_run(
            create_dryer_run_payload(
                ctx["unit"]["id"], lots[2][0]["id"], lots[2][1]["id"],
                scheduled_start="2026-09-05T12:00:00Z",
                scheduled_end="2026-09-05T13:00:00Z"),
            operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_RUN_OVERLAP, expected_status=409)


class TestEnergyVariants:
    """Same 4.0 h duration and 7.5 points removed; metered vs estimated."""

    def _metered_run_completed(self):
        ctx = setup_dried_lot_scenario(
            with_schedule=True, sample_moisture_pct=22.5, foreign_material_pct=2.0,
            meter_start=1200.0, meter_end=1265.0, scale_out=9050, discharge=15.0)
        return ctx

    def test_metered_variant_uses_meter_delta(self, api, manager_headers):
        """PRD §3.5: "By default — `energy_estimated` false — the operator
        supplies the closing `meter_end_therms`, which must be strictly greater
        than `meter_start_therms` or the completion is rejected with
        `ERR_METER_READING_INVALID` (HTTP 422); the run's `fuel_therms` is then
        the meter delta."
        PRD §3.5: "Either way, the pass-through prices marginally against the
        schedule: therms up to `energy_t1_limit_therms` bill at
        `energy_t1_rate_cents_per_therm`, and any therms beyond the breakpoint
        bill at `energy_t2_rate_cents_per_therm`; the sum, rounded half up to
        whole cents, becomes the run's `energy_charge_cents`."

        Design: Difficulty/dual_variant_calc/energy_metered_vs_estimated_burn
        """
        ctx = self._metered_run_completed()
        run = ctx["run"]
        assert run["fuel_therms"] == pytest.approx(65.0)
        # 60*85 + 5*95 = 5575
        assert run["energy_charge_cents"] == 5575

    def test_estimated_variant_uses_burn_rate(self, api, manager_headers):
        """PRD §3.5: "When `energy_estimated` is true — the meter-failure
        provision — fuel is derived instead: the run's duration in hours
        (`actual_end` minus `actual_start`, in seconds, divided by 3600),
        multiplied by the schedule's `est_therms_per_hour` burn rate, multiplied
        by one plus `est_point_factor` times the points removed, where points
        removed are the lot's `intake_moisture_pct` minus the run's
        `discharge_moisture_pct`."
        PRD §3.5: "The estimated variant performs no intermediate rounding, and
        the two variants legitimately produce different charges for the same run
        parameters."

        Design: Difficulty/dual_variant_calc/energy_metered_vs_estimated_burn
        """
        ctx = setup_base(with_schedule=True)
        # Metered twin first (clock moves forward monotonically): 08:00 -> 12:00.
        metered = create_dried_lot(
            ctx["cust"]["id"], ctx["unit"]["id"],
            sample_moisture_pct=22.5, foreign_material_pct=2.0,
            run_start="2026-09-05T08:00:00Z", run_end="2026-09-05T12:00:00Z",
            meter_start=1200.0, meter_end=1265.0, scale_out=9050, discharge=15.0)
        # 4.0 h estimated run: 13:00 -> 17:00 on 2026-09-05.
        dried = create_dried_lot(
            ctx["cust"]["id"], ctx["unit"]["id"],
            sample_moisture_pct=22.5, foreign_material_pct=2.0,
            run_start="2026-09-05T13:00:00Z", run_end="2026-09-05T17:00:00Z",
            meter_start=500.0, scale_out=9050, discharge=15.0,
            energy_estimated=True)
        run = dried["run"]
        # 4.0 * 12.5 * (1 + 0.05*7.5) = 68.75 therms, unrounded
        assert run["fuel_therms"] == pytest.approx(68.75)
        # 60*85 + 8.75*95 = 5931.25 -> 5931
        assert run["energy_charge_cents"] == 5931
        # Same duration and points as the metered 65.0-therm twin, different charge.
        assert metered["run"]["energy_charge_cents"] == 5575
        assert run["energy_charge_cents"] != metered["run"]["energy_charge_cents"]


class TestShrinkReconciliation:
    """Provisional formula weight vs certified scale weight on one lot."""

    def test_provisional_estimate_at_certification(self, api, manager_headers):
        """PRD §3.2: "The water-shrink percentage is the lot's intake moisture
        minus its target moisture, divided by one hundred minus the target
        moisture, the quotient multiplied by one hundred. The
        `provisional_shrink_pct` is that water shrink plus a handling allowance
        of half a percentage point, kept at full precision. The
        `provisional_dry_weight_lbs` is the wet net weight multiplied by one
        minus the provisional shrink percentage divided by one hundred, rounded
        half up to whole pounds."

        Design: Difficulty/dual_variant_calc/shrink_provisional_formula_vs_certified_scale
        """
        ctx = setup_base(with_unit=False)
        lot, _test = create_tested_lot(
            ctx["cust"]["id"], sample_moisture_pct=22.5, target_moisture_pct=15.0,
            foreign_material_pct=4.2, gross_weight_lbs=44000, tare_weight_lbs=34000)
        # water 7.5/85*100 + 0.5 = 9.323529...; 10000*(1-0.09323529) -> 9068
        assert lot["provisional_dry_weight_lbs"] == 9068

    def test_certified_scale_replaces_provisional(self, api, manager_headers):
        """PRD §3.5: "The lot's `final_dry_weight_lbs` takes the run's
        `scale_out_weight_lbs`; its `final_shrink_pct` is the wet net weight
        minus the final dry weight, divided by the wet net weight, the quotient
        multiplied by one hundred and rounded half up to two decimal places; and
        its `shrink_variance_lbs` is `provisional_dry_weight_lbs` minus
        `final_dry_weight_lbs` — a positive variance means the formula
        over-estimated the dry weight."
        PRD §3.5: "With no `RESERVED` storage agreement for the lot, completion
        moves it `DRYING` → `DRIED` and increments its version."

        Design: Difficulty/dual_variant_calc/shrink_provisional_formula_vs_certified_scale
        """
        ctx = setup_dried_lot_scenario(
            with_schedule=True, sample_moisture_pct=22.5, foreign_material_pct=4.2,
            scale_out=9050, discharge=15.0, meter_start=1200.0, meter_end=1265.0)
        lot = ctx["lot"]
        assert lot["final_dry_weight_lbs"] == 9050
        assert lot["final_shrink_pct"] == pytest.approx(9.50)
        # provisional 9068 - final 9050 -> positive variance 18
        assert lot["provisional_dry_weight_lbs"] == 9068
        assert lot["shrink_variance_lbs"] == 18
        assert lot["provisional_dry_weight_lbs"] != lot["final_dry_weight_lbs"]
        assert lot["status"] == "DRIED"
