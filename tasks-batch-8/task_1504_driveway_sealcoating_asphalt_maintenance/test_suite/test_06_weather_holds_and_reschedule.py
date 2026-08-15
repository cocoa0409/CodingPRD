"""Weather-driven holds, sheet re-publish, reschedule with OCC, and the
start-time temperature boundary."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_quote,
    add_accepted_job,
    assert_displacement_plan,
    assert_instant_equal,
    clear_plan_for,
    create_quote,
    create_route_sheet,
    find_work_order_for_quote,
    get_displacement_plan,
    get_route_sheet,
    get_work_order,
    post_weather_snapshot,
    reschedule_work_order,
    schedule_onto_sheet,
    send_notice,
    send_quote,
    set_clock,
    setup_accepted_job,
    setup_cleared_job,
    setup_held_job,
    setup_scheduled_job,
    validate_error,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
CREW_LEAD = TEST_USERS["crew_lead_headers"]

SEAL_ONLY = {"include_crack_fill": False, "include_patch": False}


class TestWeatherSnapshotHoldCascade:
    """A failing snapshot that is the latest for its date drives a depth-3
    cascade: sheet -> work order -> displacement plan."""

    def test_sheet_and_work_order_hold_with_retained_booking(self, api):
        """PRD §2.8: "When a newly posted snapshot is the latest for its
        target date and that snapshot shows either a precipitation probability
        strictly greater than 60 percent or a minimum temperature strictly
        below 40 degrees Fahrenheit, every published route sheet whose service
        date matches that target date is forced into `WEATHER_HOLD`; every
        scheduled work order on such a sheet follows into `WEATHER_HOLD`
        (retaining its material reservation and route booking)".

        Design: Difficulty/transitive_cascade/weather_snapshot_hold_cascade
        """
        ctx = setup_held_job(
            hold_snapshot_overrides={
                "min_temp_f": 58, "max_temp_f": 70,
                "precip_probability_pct": 80, "precipitation_mm": 4,
            }
        )
        assert ctx["sheet"]["status"] == "WEATHER_HOLD", (
            f"link 1: snapshot -> sheet, got {ctx['sheet']['status']}"
        )
        assert ctx["work_order"]["execution_status"] == "WEATHER_HOLD", (
            f"link 2: sheet -> work order, got {ctx['work_order']['execution_status']}"
        )
        assert ctx["work_order"]["reserved_gallons"] == 17, (
            "the material reservation is retained through the hold"
        )
        assert ctx["sheet"]["booked_sqft"] == 1200, (
            "the route booking is retained through the hold"
        )

    def test_displacement_plan_marked_stale(self, api):
        """PRD §2.8: "each affected work order's displacement plan, if it had
        already reached a notified or cleared state, is marked `STALE`,
        because the access window it described is no longer trustworthy."

        Design: Difficulty/transitive_cascade/weather_snapshot_hold_cascade
        """
        ctx = setup_held_job(
            hold_snapshot_overrides={
                "min_temp_f": 58, "max_temp_f": 70,
                "precip_probability_pct": 80, "precipitation_mm": 4,
            }
        )
        assert ctx["plan"]["status"] == "STALE", (
            f"link 3: work order -> plan, got {ctx['plan']['status']}"
        )
        assert_displacement_plan(ctx["plan"])


class TestRouteSheetRepublish:
    def test_republish_keeps_jobs_held(self, api):
        """PRD §3.5: "a weather-held sheet may be re-published, but
        re-publishing does not auto-return its work orders — each one stays
        `WEATHER_HOLD` until individually rescheduled."

        Design: Corner/state_machines/route_sheet_republish_keeps_jobs_held
        """
        ctx = setup_held_job(
            lot_kind="RESIDENTIAL_DRIVEWAY",
            address="1 Elm St",
            measured_area_sqft=900,
            crack_linear_ft=10,
            pothole_count=1,
            pothole_area_sqft=2,
            window_start_hour=7,
            window_end_hour=10,
            drive_minutes_est=15,
            vehicles_to_move=1,
            hold_snapshot_overrides={"min_temp_f": 38, "max_temp_f": 60,
                                     "precip_probability_pct": 20},
        )
        assert ctx["sheet"]["status"] == "WEATHER_HOLD"
        assert ctx["work_order"]["execution_status"] == "WEATHER_HOLD"

        republished = validate_success(
            api.publish_route_sheet(ctx["sheet"]["id"], DISPATCHER)
        )
        assert republished["status"] == "PUBLISHED"
        wo_after = get_work_order(ctx["work_order"]["id"])
        assert wo_after["execution_status"] == "WEATHER_HOLD", (
            "jobs are individually rescheduled, never auto-released"
        )


class TestRescheduleRenoticeCycle:
    def test_reschedule_resets_plan_and_fresh_notice_succeeds(self, api):
        """PRD §3.5: "The displacement plan's access-block window is
        recomputed, and a plan in `NOTICE_SENT`, `CLEARED`, or `STALE` resets
        to `NOTICE_PENDING` with `notice_sent_at` cleared, because occupants
        must be re-notified against the new window." PRD §3.6: "A `Dispatcher`
        sends the notice from `NOTICE_PENDING` or `STALE` (else
        `ERR_PLAN_NOT_NOTICABLE`), and the notice must go out with at least
        48 hours of lead time" — catalogued in PRD §5 as
        `ERR_PLAN_NOT_NOTIFIABLE` | 409.

        Design: Corner/state_machines/displacement_reschedule_renotice_cycle
        """
        ctx = setup_held_job(
            lot_kind="RESIDENTIAL_DRIVEWAY",
            address="1 Elm St",
            measured_area_sqft=900,
            crack_linear_ft=10,
            pothole_count=1,
            pothole_area_sqft=2,
            window_start_hour=7,
            window_end_hour=10,
            drive_minutes_est=15,
            vehicles_to_move=2,
        )
        assert ctx["plan"]["status"] == "STALE"

        sheet2 = create_route_sheet(ctx["crew"]["id"], "2026-08-14")
        post_weather_snapshot(
            "2026-08-14", min_temp_f=66, max_temp_f=83, precip_probability_pct=5
        )
        rescheduled = reschedule_work_order(
            ctx["work_order"]["id"], sheet2["id"], "2026-08-14",
            window_start_hour=8, window_end_hour=11, drive_minutes_est=20,
        )
        assert rescheduled["execution_status"] == "SCHEDULED"
        assert rescheduled["scheduled_date"] == "2026-08-14"

        plan = get_displacement_plan(ctx["plan"]["id"])
        assert plan["status"] == "NOTICE_PENDING"
        # block start recomputed to the new date at window_start_hour UTC
        assert_instant_equal(plan["access_block_start"], "2026-08-14T08:00:00Z")
        assert plan["notice_sent_at"] is None

        # Clock is still 2026-08-01: 48h lead time to 2026-08-14 is satisfied.
        noticed = send_notice(plan["id"])
        assert noticed["status"] == "NOTICE_SENT"


class TestRescheduleOcc:
    def test_stale_work_order_version_rejected_then_fresh_succeeds(self, api):
        """PRD §2.6: "if another writer has advanced the work order's version
        since the client last read it, the reschedule is rejected with
        `ERR_STALE_VERSION` (HTTP 412)." PRD §3.5: "The compensating side
        releases the old booking first: the old sheet's booked area and drive
        minutes shrink, the old lot's reservation returns and its ledger
        recomputes, and then the new booking, reservation, and cascades apply
        exactly as a fresh schedule."

        Design: Corner/cross_cutting_layers/occ_reschedule_stale_work_order_version
        """
        ctx = setup_scheduled_job(
            lot_kind="RESIDENTIAL_DRIVEWAY",
            address="1 Elm St",
            measured_area_sqft=900,
            crack_linear_ft=10,
            pothole_count=1,
            pothole_area_sqft=2,
            window_start_hour=7,
            window_end_hour=10,
            drive_minutes_est=15,
            vehicles_to_move=1,
        )
        stale_version = ctx["work_order"]["version"]
        # The hold cascade advances the work order's version.
        post_weather_snapshot(
            "2026-08-10", min_temp_f=44, max_temp_f=60,
            precip_probability_pct=90, precipitation_mm=5,
        )
        held = get_work_order(ctx["work_order"]["id"])
        assert held["execution_status"] == "WEATHER_HOLD"
        assert held["version"] > stale_version

        sheet2 = create_route_sheet(ctx["crew"]["id"], "2026-08-14")
        post_weather_snapshot(
            "2026-08-14", min_temp_f=66, max_temp_f=83, precip_probability_pct=5
        )
        resp = api.reschedule_work_order(
            ctx["work_order"]["id"],
            {
                "route_sheet_id": sheet2["id"],
                "scheduled_date": "2026-08-14",
                "window_start_hour": 8,
                "window_end_hour": 11,
                "drive_minutes_est": 20,
                "expected_work_order_version": stale_version,
            },
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        rescheduled = reschedule_work_order(
            ctx["work_order"]["id"], sheet2["id"], "2026-08-14",
            window_start_hour=8, window_end_hour=11, drive_minutes_est=20,
        )
        assert rescheduled["execution_status"] == "SCHEDULED"
        assert rescheduled["version"] > held["version"], (
            "a successful reschedule increments the work order version once more"
        )
        old_sheet = get_route_sheet(ctx["sheet"]["id"])
        assert old_sheet["booked_sqft"] == 0, "old booking released"
        new_sheet = get_route_sheet(sheet2["id"])
        assert new_sheet["booked_sqft"] == 900, "new booking applied"


class TestStartTemperatureBoundary:
    """Observed minimum temperature exactly at vs one-tenth below the
    material's application envelope on the service morning."""

    def _setup_two_cleared_jobs(self, api):
        ctx = setup_cleared_job(
            address="100 Commerce Way",
            measured_area_sqft=1000,
            crack_linear_ft=0,
            pothole_count=0,
            pothole_area_sqft=0,
            oil_spot_area_sqft=0,
            quote_overrides=SEAL_ONLY,
            window_start_hour=7,
            window_end_hour=10,
            drive_minutes_est=15,
            vehicles_to_move=1,
            delivered_gallons=200,
        )
        sub2 = add_accepted_job(
            ctx, address="300 Commerce Way", measured_area_sqft=1000,
            quote_overrides=SEAL_ONLY,
        )
        sheet2 = create_route_sheet(ctx["crew"]["id"], "2026-08-11")
        post_weather_snapshot("2026-08-11", min_temp_f=65)
        job2 = schedule_onto_sheet(
            ctx, sub2, sheet=sheet2, service_date="2026-08-11",
            window_start_hour=7, window_end_hour=10, vehicles_to_move=1,
        )
        confirm2 = clear_plan_for(job2["work_order"]["id"])
        # Same-instant morning observations, one per service date.
        post_weather_snapshot(
            "2026-08-10", min_temp_f=50.0, max_temp_f=68, source="OBSERVED"
        )
        post_weather_snapshot(
            "2026-08-11", min_temp_f=49.9, max_temp_f=67, source="OBSERVED"
        )
        ctx["job2"] = job2
        ctx["plan2"] = confirm2
        return ctx

    def test_exact_minimum_temperature_passes(self, api):
        """PRD §2.8: "If the latest snapshot shows a minimum temperature below
        the material's `min_apply_temp_f`, or a precipitation probability
        above the material's `max_precip_probability_pct`, the operation fails
        with `ERR_WEATHER_WINDOW_VIOLATION`."

        Design: Difficulty/boundary_precision_check/start_temperature_exact_boundary
        """
        ctx = self._setup_two_cleared_jobs(api)
        set_clock("2026-08-10T07:00:00Z")
        started = validate_success(
            api.start_work_order(ctx["work_order"]["id"], CREW_LEAD)
        )
        assert started["execution_status"] == "IN_PROGRESS", (
            "50.0F is not below the 50F minimum — the boundary is inclusive"
        )

    def test_one_tenth_below_minimum_rejected(self, api):
        """PRD §2.8: "If the latest snapshot shows a minimum temperature below
        the material's `min_apply_temp_f`, or a precipitation probability
        above the material's `max_precip_probability_pct`, the operation fails
        with `ERR_WEATHER_WINDOW_VIOLATION`."

        Design: Difficulty/boundary_precision_check/start_temperature_exact_boundary
        """
        ctx = self._setup_two_cleared_jobs(api)
        set_clock("2026-08-11T07:00:00Z")
        resp = api.start_work_order(ctx["job2"]["work_order"]["id"], CREW_LEAD)
        validate_error(resp, ApiErrorId.ERR_WEATHER_WINDOW_VIOLATION, 422)
        wo_after = get_work_order(ctx["job2"]["work_order"]["id"])
        assert wo_after["execution_status"] == "SCHEDULED", (
            "a failed start leaves the work order SCHEDULED"
        )
