"""Crew utilization (projected vs realized variants) and immediate
read-after-write consistency."""
from test_helpers import (
    TEST_USERS,
    add_accepted_job,
    clear_plan_for,
    create_crew,
    create_material_lot,
    create_route_sheet,
    get_material_lot,
    get_route_sheet,
    get_work_order,
    post_weather_snapshot,
    schedule_onto_sheet,
    set_clock,
    setup_accepted_job,
    setup_scheduled_job,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
CREW_LEAD = TEST_USERS["crew_lead_headers"]

SEAL_ONLY = {"include_crack_fill": False, "include_patch": False}


class TestCrewUtilizationVariants:
    """One crew, two August sheets of 8000: job 1 (quoted 1200) completes with
    actual 1250; job 2 (quoted 2000) is still scheduled."""

    def _setup(self, api):
        ctx = setup_accepted_job(
            address="100 Commerce Way", measured_area_sqft=1200,
            crack_linear_ft=0, pothole_count=0, pothole_area_sqft=0,
            oil_spot_area_sqft=0, quote_overrides=SEAL_ONLY,
        )
        ctx["lot"] = create_material_lot(ctx["material"]["id"], delivered_gallons=500)
        ctx["crew"] = create_crew()
        sheet1 = create_route_sheet(ctx["crew"]["id"], "2026-08-10")
        sheet2 = create_route_sheet(ctx["crew"]["id"], "2026-08-11")
        post_weather_snapshot("2026-08-10")
        post_weather_snapshot("2026-08-11", min_temp_f=66, precip_probability_pct=5)
        sub2 = add_accepted_job(
            ctx, address="200 Commerce Way", measured_area_sqft=2000,
            quote_overrides=SEAL_ONLY,
        )
        job1 = schedule_onto_sheet(
            ctx, {"work_order": ctx["work_order"]}, sheet=sheet1,
            service_date="2026-08-10", window_start_hour=7, window_end_hour=11,
            drive_minutes_est=20, vehicles_to_move=2,
        )
        job2 = schedule_onto_sheet(
            ctx, sub2, sheet=sheet2, service_date="2026-08-11",
            window_start_hour=7, window_end_hour=11, drive_minutes_est=25,
            vehicles_to_move=4,
        )
        # Run job 1 to completion with actual area 1250.
        clear_plan_for(job1["work_order"]["id"])
        set_clock("2026-08-10T07:00:00Z")
        validate_success(api.start_work_order(job1["work_order"]["id"], CREW_LEAD))
        finished = validate_success(
            api.finish_work_order(
                job1["work_order"]["id"],
                {
                    "actual_area_sqft": 1250,
                    "actual_crack_ft": 0,
                    "actual_pothole_area_sqft": 0,
                    "actual_stripe_ft": 0,
                    "gallons_used": 17,
                },
                CREW_LEAD,
            )
        )
        set_clock(finished["cure_until"])
        validate_success(api.complete_work_order(job1["work_order"]["id"], CREW_LEAD))
        ctx["job2"] = job2
        return ctx

    def test_projected_variant_counts_booked_demand(self, api):
        """PRD §3.11: "The projected figure divides by that capacity the
        summed `quoted_area_sqft` of work orders in scheduled, weather-held,
        in-progress, curing, or completed states: forward-looking booked
        demand, including jobs that have not run yet."

        Design: Difficulty/dual_variant_calc/crew_utilization_projected_vs_realized
        """
        ctx = self._setup(api)
        report = validate_success(
            api.get_crew_utilization(ctx["crew"]["id"], "2026-08", DISPATCHER)
        )
        assert report["capacity_sqft"] == 16000, (
            f"two non-cancelled sheets of 8000, got {report['capacity_sqft']}"
        )
        assert report["projected_sqft"] == 3200, (
            f"quoted 1200 (completed) + 2000 (scheduled), got {report['projected_sqft']}"
        )
        assert report["projected_utilization_pct"] == 20.0, (
            f"3200 / 16000 = 20.0, got {report['projected_utilization_pct']}"
        )

    def test_realized_variant_counts_completed_actuals_only(self, api):
        """PRD §3.11: "The realized figure instead sums `actual_area_sqft`
        over completed and closed work orders only. A month of
        scheduled-but-unfinished work therefore reads high on projected and
        low on realized".

        Design: Difficulty/dual_variant_calc/crew_utilization_projected_vs_realized
        """
        ctx = self._setup(api)
        report = validate_success(
            api.get_crew_utilization(ctx["crew"]["id"], "2026-08", DISPATCHER)
        )
        assert report["realized_sqft"] == 1250, (
            f"only the completed job's actual area counts, got {report['realized_sqft']}"
        )
        assert report["realized_utilization_pct"] == 7.8, (
            f"round_half_up(1250 / 16000 * 100, 1) = 7.8, got {report['realized_utilization_pct']}"
        )
        assert report["projected_utilization_pct"] > report["realized_utilization_pct"], (
            "forward-looking and realized variants diverge on unfinished work"
        )


class TestUtilizationEmptyMonth:
    def test_cancelled_sheet_month_returns_zeros(self, api):
        """PRD §3.11: "The report covers the crew's sheets whose service date
        falls in that month, excluding cancelled sheets" and "both are zero
        when the month's capacity sums to zero."

        Design: Corner/calculations/utilization_empty_month_returns_zeros
        """
        crew = create_crew(crew_name="Crew Echo", home_zone="East",
                           daily_capacity_sqft=5000)
        sheet = create_route_sheet(crew["id"], "2026-09-03", publish=False)
        validate_success(api.cancel_route_sheet(sheet["id"], DISPATCHER))

        report = validate_success(
            api.get_crew_utilization(crew["id"], "2026-09", DISPATCHER)
        )
        assert report["capacity_sqft"] == 0, "the CANCELLED sheet is excluded"
        assert report["projected_utilization_pct"] == 0.0
        assert report["realized_utilization_pct"] == 0.0


class TestImmediateConsistency:
    def test_reads_observe_schedule_effects_immediately(self, api):
        """PRD §3.5: "On a successful schedule the world shifts in several
        places at once. The work order moves to `SCHEDULED` with its `version`
        incremented and `reserved_gallons` set per the formula. The lot's
        `reserved_gallons` grows by that amount, a first reservation flips the
        lot from `RECEIVED` to `IN_USE`, and the lot's on-hand gallons and
        `reorder_flag` recompute. The sheet's `booked_sqft` grows by
        `quoted_area_sqft`, `total_drive_minutes` grows by
        `drive_minutes_est`, `open_capacity_sqft` recomputes, and the sheet's
        `version` increments."

        Design: Corner/consistency_model/immediate_consistency_after_mutation
        """
        ctx = setup_scheduled_job(
            lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St",
            measured_area_sqft=900, crack_linear_ft=10, pothole_count=1,
            pothole_area_sqft=2, window_start_hour=7, window_end_hour=10,
            drive_minutes_est=15, vehicles_to_move=1,
        )
        sheet = get_route_sheet(ctx["sheet"]["id"])
        assert sheet["booked_sqft"] == 900
        lot = get_material_lot(ctx["lot"]["id"])
        assert lot["reserved_gallons"] == 13, (
            f"ceil(900 * 1 * 1.10 / 80) = 13, got {lot['reserved_gallons']}"
        )
        assert lot["status"] == "IN_USE"
        wo = get_work_order(ctx["work_order"]["id"])
        assert wo["execution_status"] == "SCHEDULED"
        assert wo["reserved_gallons"] == 13
