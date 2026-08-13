"""Execution lifecycle: displacement gating, cure window, cancellation
compensation, and notice lead time."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_displacement_plan,
    assert_instant_equal,
    confirm_cleared,
    get_displacement_plan,
    get_material_lot,
    get_route_sheet,
    get_work_order,
    post_weather_snapshot,
    send_notice,
    set_clock,
    setup_cleared_job,
    setup_in_progress_job,
    setup_scheduled_job,
    validate_error,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
CREW_LEAD = TEST_USERS["crew_lead_headers"]

RESIDENTIAL_900 = dict(
    lot_kind="RESIDENTIAL_DRIVEWAY",
    address="1 Elm St",
    measured_area_sqft=900,
    crack_linear_ft=10,
    pothole_count=1,
    pothole_area_sqft=2,
)


class TestStartRequiresDisplacementCleared:
    def test_start_blocked_until_plan_cleared(self, api):
        """PRD §3.7: "Starting requires `SCHEDULED` status (else
        `ERR_WORK_ORDER_NOT_STARTABLE`), requires the current clock date to
        equal `scheduled_date` (else `ERR_DATE_IN_PAST`), requires the
        displacement plan to be `CLEARED` (else `ERR_DISPLACEMENT_NOT_CLEARED`)".

        Design: Difficulty/cross_entity_state_dependency/start_requires_displacement_cleared
        """
        ctx = setup_scheduled_job()
        send_notice(ctx["plan"]["id"])  # NOTICE_SENT, not yet CLEARED
        set_clock("2026-08-10T07:00:00Z")
        resp = api.start_work_order(ctx["work_order"]["id"], CREW_LEAD)
        validate_error(resp, ApiErrorId.ERR_DISPLACEMENT_NOT_CLEARED, 409)
        assert get_work_order(ctx["work_order"]["id"])["execution_status"] == "SCHEDULED"

    def test_start_succeeds_after_confirm_cleared(self, api):
        """PRD §3.6: "Once occupants confirm the vehicles are moved, the
        dispatcher confirms the plan from `NOTICE_SENT` to `CLEARED`". PRD
        §3.7: "The work order moves to `IN_PROGRESS` and `started_at` is
        stamped."

        Design: Difficulty/cross_entity_state_dependency/start_requires_displacement_cleared
        """
        ctx = setup_scheduled_job()
        send_notice(ctx["plan"]["id"])
        set_clock("2026-08-10T07:00:00Z")
        resp = api.start_work_order(ctx["work_order"]["id"], CREW_LEAD)
        validate_error(resp, ApiErrorId.ERR_DISPLACEMENT_NOT_CLEARED, 409)

        confirm_cleared(ctx["plan"]["id"])
        started = validate_success(api.start_work_order(ctx["work_order"]["id"], CREW_LEAD))
        assert started["execution_status"] == "IN_PROGRESS"
        assert started["started_at"] is not None


class TestCureGate:
    def test_complete_before_and_at_cure_until(self, api):
        """PRD §3.7: "Completion — again by the crew lead — requires `CURING`,
        requires the current clock to have reached `cure_until` (else
        `ERR_CURE_INCOMPLETE`)".

        Design: Corner/state_machines/complete_before_cure_until_rejected
        """
        ctx = setup_in_progress_job(
            **RESIDENTIAL_900, window_start_hour=7, window_end_hour=10,
            drive_minutes_est=15, vehicles_to_move=1,
        )
        finished = validate_success(
            api.finish_work_order(
                ctx["work_order"]["id"],
                {
                    "actual_area_sqft": 900,
                    "actual_crack_ft": 10,
                    "actual_pothole_area_sqft": 2,
                    "actual_stripe_ft": 0,
                    "gallons_used": 12,
                },
                CREW_LEAD,
            )
        )
        # 65F dry forecast: base 48h unadjusted from finished 2026-08-10T07:00Z.
        assert_instant_equal(finished["cure_until"], "2026-08-12T07:00:00Z")

        set_clock("2026-08-12T06:59:59Z")
        resp = api.complete_work_order(ctx["work_order"]["id"], CREW_LEAD)
        validate_error(resp, ApiErrorId.ERR_CURE_INCOMPLETE, 422)

        set_clock("2026-08-12T07:00:00Z")
        completed = validate_success(api.complete_work_order(ctx["work_order"]["id"], CREW_LEAD))
        assert completed["execution_status"] == "COMPLETED", (
            "reaching cure_until exactly satisfies the gate"
        )


class TestCureWindowAdjustments:
    def test_cold_and_wet_observed_cure_extension(self, api):
        """PRD §3.5: "if its minimum temperature is below 55 degrees
        Fahrenheit, the base is multiplied by 1.5 and rounded up to whole
        hours; if its precipitation amount is greater than zero millimeters,
        12 hours are added on top". PRD §3.7: "The displacement plan's
        `access_block_end` finalizes to `cure_until`, so the access block now
        reflects real chemistry."

        Design: Corner/calculations/cure_window_cold_and_wet_adjustments
        """
        ctx = setup_in_progress_job(
            **RESIDENTIAL_900, window_start_hour=7, window_end_hour=10,
            drive_minutes_est=15, vehicles_to_move=1,
        )
        # Observed snapshot for the finish date: 50F (<55) and 3mm rain.
        post_weather_snapshot(
            "2026-08-10", min_temp_f=50, max_temp_f=64,
            precip_probability_pct=30, precipitation_mm=3, source="OBSERVED",
        )
        finished = validate_success(
            api.finish_work_order(
                ctx["work_order"]["id"],
                {
                    "actual_area_sqft": 900,
                    "actual_crack_ft": 10,
                    "actual_pothole_area_sqft": 2,
                    "actual_stripe_ft": 0,
                    "gallons_used": 12,
                },
                CREW_LEAD,
            )
        )
        # ceil(48 * 1.5) + 12 = 84h after 2026-08-10T07:00Z
        assert_instant_equal(finished["cure_until"], "2026-08-13T19:00:00Z")
        plan = get_displacement_plan(ctx["plan"]["id"])
        assert_instant_equal(plan["access_block_end"], "2026-08-13T19:00:00Z")


class TestCancelFromInProgress:
    def test_cancel_in_progress_rejected(self, api):
        """PRD §3.5: "Cancelling a work order — allowed from `PENDING`,
        `SCHEDULED`, or `WEATHER_HOLD`, else
        `ERR_WORK_ORDER_NOT_CANCELLABLE`".

        Design: Corner/state_machines/work_order_cancel_from_in_progress_rejected
        """
        ctx = setup_in_progress_job(
            **RESIDENTIAL_900, window_start_hour=7, window_end_hour=10,
            drive_minutes_est=15, vehicles_to_move=1,
        )
        resp = api.cancel_work_order(ctx["work_order"]["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_WORK_ORDER_NOT_CANCELLABLE, 409)

        wo_after = get_work_order(ctx["work_order"]["id"])
        assert wo_after["execution_status"] == "IN_PROGRESS"
        lot_after = get_material_lot(ctx["lot"]["id"])
        assert lot_after["reserved_gallons"] == 13, (
            f"ceil(900 * 1 * 1.10 / 80) = 13 gallons stay reserved, got {lot_after['reserved_gallons']}"
        )


class TestCancelReleaseCascade:
    """Lot delivered 100 with reorder threshold 90: the 17-gallon reservation
    trips the flag; cancelling releases everything."""

    def test_cancel_releases_lot_ledger_and_restores_received(self, api):
        """PRD §3.5: "the lot's `reserved_gallons` drops by the reservation,
        the work order's reservation zeroes, the lot ledger recomputes (which
        may clear the reorder flag), and a lot left `IN_USE` with both
        reserved and consumed gallons at zero returns to `RECEIVED`".

        Design: Difficulty/transitive_cascade/cancel_release_cascade
        """
        ctx = setup_scheduled_job(reorder_threshold_gallons=90)
        lot_pre = get_material_lot(ctx["lot"]["id"])
        assert lot_pre["status"] == "IN_USE"
        assert lot_pre["reserved_gallons"] == 17
        assert lot_pre["on_hand_gallons"] == 83
        assert lot_pre["reorder_flag"] is True, "83 <= 90 trips the reorder flag"

        validate_success(api.cancel_work_order(ctx["work_order"]["id"], DISPATCHER))
        lot = get_material_lot(ctx["lot"]["id"])
        assert lot["reserved_gallons"] == 0, "link 1: reservation released"
        assert lot["on_hand_gallons"] == 100
        assert lot["reorder_flag"] is False, "link 2: recompute clears the flag"
        assert lot["status"] == "RECEIVED", (
            "zero reserved and zero consumed returns the lot to RECEIVED"
        )

    def test_cancel_releases_sheet_booking_and_cancels_plan(self, api):
        """PRD §3.5: "Cancelling a work order — allowed from `PENDING`,
        `SCHEDULED`, or `WEATHER_HOLD`, else `ERR_WORK_ORDER_NOT_CANCELLABLE`
        — runs the mirror-image compensation: the sheet's booking releases and
        its open capacity recomputes; the lot's `reserved_gallons` drops by
        the reservation, the work order's reservation zeroes, the lot ledger
        recomputes (which may clear the reorder flag), and a lot left `IN_USE`
        with both reserved and consumed gallons at zero returns to `RECEIVED`;
        the displacement plan, whatever its state, moves to `CANCELLED`."

        Design: Difficulty/transitive_cascade/cancel_release_cascade
        """
        ctx = setup_scheduled_job(reorder_threshold_gallons=90)
        validate_success(api.cancel_work_order(ctx["work_order"]["id"], DISPATCHER))

        sheet = get_route_sheet(ctx["sheet"]["id"])
        assert sheet["booked_sqft"] == 0
        assert sheet["open_capacity_sqft"] == 8000
        plan = get_displacement_plan(ctx["plan"]["id"])
        assert plan["status"] == "CANCELLED"
        wo = get_work_order(ctx["work_order"]["id"])
        assert wo["execution_status"] == "CANCELLED"
        assert wo["reserved_gallons"] == 0


class TestNoticeLeadTime:
    def test_short_lead_time_rejected_then_timely_notice_succeeds(self, api):
        """PRD §3.6: "the notice must go out with at least 48 hours of lead
        time: the current clock plus 48 hours must not be later than
        `access_block_start`, else `ERR_NOTICE_LEAD_TIME_SHORT`."

        Design: Corner/validations/notice_lead_time_short_rejected
        """
        ctx = setup_scheduled_job(
            **RESIDENTIAL_900, window_start_hour=7, window_end_hour=10,
            drive_minutes_est=15, vehicles_to_move=1,
        )
        plan_id = ctx["plan"]["id"]
        # Access block starts 2026-08-10T07:00Z; at 2026-08-09 only 31h remain.
        set_clock("2026-08-09T00:00:00Z")
        resp = api.send_displacement_notice(plan_id, DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_NOTICE_LEAD_TIME_SHORT, 422)
        plan = get_displacement_plan(plan_id)
        assert plan["status"] == "NOTICE_PENDING"

        set_clock("2026-08-01T00:00:00Z")
        noticed = send_notice(plan_id)
        assert noticed["status"] == "NOTICE_SENT"
        assert noticed["notice_sent_at"] is not None


class TestNoticeStateMachine:
    def test_confirm_before_notice_rejected(self, api):
        """PRD §3.6: "the dispatcher confirms the plan from `NOTICE_SENT` to
        `CLEARED` (from any other state, `ERR_PLAN_NOT_NOTICED`)."

        Design: Corner/errors/displacement_confirm_before_notice_rejected
        """
        ctx = setup_scheduled_job(
            **RESIDENTIAL_900, window_start_hour=7, window_end_hour=10,
            drive_minutes_est=15, vehicles_to_move=1,
        )
        resp = api.confirm_displacement_cleared(ctx["plan"]["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_NOTICED, 409)
        plan = get_displacement_plan(ctx["plan"]["id"])
        assert plan["status"] == "NOTICE_PENDING"

    def test_renotice_after_cleared_rejected(self, api):
        """PRD §3.6: "A `Dispatcher` sends the notice from `NOTICE_PENDING` or
        `STALE` (else `ERR_PLAN_NOT_NOTICABLE`), and the notice must go out
        with at least 48 hours of lead time" — catalogued in PRD §5 as
        `ERR_PLAN_NOT_NOTIFIABLE` | 409.

        Design: Corner/errors/displacement_renotice_after_cleared_rejected
        """
        ctx = setup_cleared_job(
            **RESIDENTIAL_900, window_start_hour=7, window_end_hour=10,
            drive_minutes_est=15, vehicles_to_move=1,
        )
        assert ctx["plan"]["status"] == "CLEARED"
        resp = api.send_displacement_notice(ctx["plan"]["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_NOTIFIABLE, 409)
        plan = get_displacement_plan(ctx["plan"]["id"])
        assert plan["status"] == "CLEARED"
        assert_displacement_plan(plan)
