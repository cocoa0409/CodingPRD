"""Scheduling gates: weather precedence, season, past dates, window hours,
material lot usability, reseal interval, and sheet cancellation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_quote,
    add_accepted_job,
    assert_instant_equal,
    assert_work_order,
    create_crew,
    create_material_lot,
    create_quote,
    create_route_sheet,
    find_work_order_for_quote,
    get_work_order,
    post_weather_snapshot,
    schedule_work_order,
    send_quote,
    set_clock,
    setup_accepted_job,
    setup_completed_job,
    setup_scheduled_job,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["office_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


def _schedule_attempt(api, work_order_id, sheet_id, lot_id, scheduled_date, **overrides):
    payload = {
        "route_sheet_id": sheet_id,
        "material_lot_id": lot_id,
        "scheduled_date": scheduled_date,
        "window_start_hour": 7,
        "window_end_hour": 10,
        "drive_minutes_est": 15,
        "vehicles_to_move": 1,
    }
    payload.update(overrides)
    return api.schedule_work_order(work_order_id, payload, DISPATCHER)


class TestWeatherGatePrecedence:
    """A schedule attempt against a service date with no weather snapshot
    fails at the weather gate (PRD §2.8), ahead of the season/past-date rules
    (PRD §2.11)."""

    def _setup_sheet_without_weather(self, api):
        """Accepted job + lot + published sheet for an in-season future date,
        with no weather snapshot posted for that date. (A past-dated sheet
        cannot reach the weather gate at all: PRD §2.7 evaluates lazy state
        flips at load time, and PRD §3.5 settles a past-dated sheet with no
        active work orders to COMPLETED, so such a sheet fails gate 2 with
        ERR_ROUTE_SHEET_NOT_SCHEDULABLE before any weather check.)"""
        ctx = setup_accepted_job(lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St")
        ctx["lot"] = create_material_lot(ctx["material"]["id"])
        ctx["crew"] = create_crew()
        ctx["sheet"] = create_route_sheet(ctx["crew"]["id"], "2026-08-10")
        return ctx

    def test_failed_schedule_leaves_work_order_pending(self, api):
        """PRD §2.8: "If no snapshot exists for the service date at all, the
        operation fails with `ERR_WEATHER_DATA_MISSING`." PRD §3.4: "The work
        order is born with `execution_status` of `PENDING`, `billing_status`
        of `UNINVOICED`, and a `striping_status` of `PLANNING` when striping
        is in scope and `NOT_REQUIRED` otherwise. While pending,
        `route_sheet_id`, `material_lot_id`, and `scheduled_date` are all
        null."

        Design: Difficulty/priority_pair_validation_conflict/schedule_safety_vs_temporal
        """
        ctx = self._setup_sheet_without_weather(api)
        resp = _schedule_attempt(
            api, ctx["work_order"]["id"], ctx["sheet"]["id"], ctx["lot"]["id"],
            "2026-08-10",
        )
        validate_error(resp, ApiErrorId.ERR_WEATHER_DATA_MISSING, 422)

        after = get_work_order(ctx["work_order"]["id"])
        assert_work_order(after)
        assert after["execution_status"] == "PENDING"
        assert after["route_sheet_id"] is None
        assert after["material_lot_id"] is None
        assert after["scheduled_date"] is None


class TestSeasonGate:
    def test_schedule_outside_season_rejected(self, api):
        """PRD §2.7: "The paving season is fixed: sealcoating work may only be
        scheduled on dates whose month-and-day fall within the inclusive
        window from April 1 through October 31. A scheduling request naming a
        date outside that window is rejected with `ERR_OUTSIDE_SEASON`".

        Design: Corner/validations/schedule_outside_season_rejected
        """
        ctx = setup_accepted_job(lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St")
        lot = create_material_lot(ctx["material"]["id"])
        crew = create_crew()
        sheet = create_route_sheet(crew["id"], "2026-11-02")
        post_weather_snapshot(
            "2026-11-02", min_temp_f=60, max_temp_f=70, precip_probability_pct=10
        )
        resp = _schedule_attempt(
            api, ctx["work_order"]["id"], sheet["id"], lot["id"], "2026-11-02"
        )
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_SEASON, 422)
        assert get_work_order(ctx["work_order"]["id"])["execution_status"] == "PENDING"


class TestPastDateGate:
    def test_schedule_date_in_past_rejected(self, api):
        """PRD §2.7: "a date in the past relative to the logical clock is
        rejected with `ERR_DATE_IN_PAST`."

        The past-dated sheet must stay PUBLISHED to reach the temporal gate:
        PRD §3.5 settles a past-dated sheet with no active work order to
        COMPLETED, so an active (SCHEDULED) job anchors it alive while the
        clock advances past its service date.

        Design: Corner/validations/schedule_date_in_past_rejected
        """
        ctx = setup_scheduled_job(lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St")
        sub = add_accepted_job(ctx, address="9 Elm St", measured_area_sqft=900)
        # Advance the clock past the sheet's 2026-08-10 service date; the
        # anchored SCHEDULED job keeps the sheet from closing lazily.
        set_clock("2026-08-11T00:00:00Z")
        resp = _schedule_attempt(
            api, sub["work_order"]["id"], ctx["sheet"]["id"], ctx["lot"]["id"],
            "2026-08-10",
        )
        validate_error(resp, ApiErrorId.ERR_DATE_IN_PAST, 422)


class TestWindowHours:
    def test_end_not_after_start_rejected(self, api):
        """PRD §3.5: "The window hours themselves must be sane: start between
        6 and 19 inclusive, end between 7 and 20 inclusive, end strictly after
        start — violations are `ERR_INVALID_WINDOW_HOURS`."

        Design: Corner/validations/invalid_window_hours_rejected
        """
        ctx = setup_accepted_job(lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St")
        lot = create_material_lot(ctx["material"]["id"])
        crew = create_crew()
        sheet = create_route_sheet(crew["id"], "2026-08-10")
        post_weather_snapshot("2026-08-10")
        resp = _schedule_attempt(
            api,
            ctx["work_order"]["id"],
            sheet["id"],
            lot["id"],
            "2026-08-10",
            window_start_hour=12,
            window_end_hour=10,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW_HOURS, 400)


class TestMaterialLotUsability:
    def _setup_two_lots(self, api):
        """Accepted job; lot_q quarantined, lot_r received; sheet + weather."""
        ctx = setup_accepted_job()
        lot_q = create_material_lot(ctx["material"]["id"])
        validate_success(api.quarantine_material_lot(lot_q["id"], ADMIN))
        lot_r = create_material_lot(ctx["material"]["id"], received_on="2026-07-16")
        crew = create_crew()
        sheet = create_route_sheet(crew["id"], "2026-08-10")
        post_weather_snapshot("2026-08-10")
        ctx.update({"lot_q": lot_q, "lot_r": lot_r, "crew": crew, "sheet": sheet})
        return ctx

    def test_quarantined_lot_rejected(self, api):
        """PRD §3.5: "The material lot must be `RECEIVED` or `IN_USE` (else
        `ERR_MATERIAL_LOT_UNAVAILABLE`)". PRD §2.9: "referencing a quarantined
        or depleted lot for new work is rejected with
        `ERR_MATERIAL_LOT_UNAVAILABLE`."

        Design: Difficulty/cross_entity_state_dependency/schedule_requires_usable_material_lot
        """
        ctx = self._setup_two_lots(api)
        resp = _schedule_attempt(
            api, ctx["work_order"]["id"], ctx["sheet"]["id"], ctx["lot_q"]["id"],
            "2026-08-10", window_end_hour=11, drive_minutes_est=20, vehicles_to_move=3,
        )
        validate_error(resp, ApiErrorId.ERR_MATERIAL_LOT_UNAVAILABLE, 409)
        assert get_work_order(ctx["work_order"]["id"])["execution_status"] == "PENDING"

    def test_received_lot_succeeds_after_quarantined_rejection(self, api):
        """PRD §3.5: "The material lot must be `RECEIVED` or `IN_USE` (else
        `ERR_MATERIAL_LOT_UNAVAILABLE`), must stock the same material the
        quote specified, and its on-hand gallons must cover the reservation
        (else `ERR_INSUFFICIENT_MATERIAL`)."

        Design: Difficulty/cross_entity_state_dependency/schedule_requires_usable_material_lot
        """
        ctx = self._setup_two_lots(api)
        resp = _schedule_attempt(
            api, ctx["work_order"]["id"], ctx["sheet"]["id"], ctx["lot_q"]["id"],
            "2026-08-10", window_end_hour=11, drive_minutes_est=20, vehicles_to_move=3,
        )
        validate_error(resp, ApiErrorId.ERR_MATERIAL_LOT_UNAVAILABLE, 409)

        scheduled = schedule_work_order(
            ctx["work_order"]["id"], ctx["sheet"]["id"], ctx["lot_r"]["id"],
            "2026-08-10", window_end_hour=11, drive_minutes_est=20, vehicles_to_move=3,
        )
        assert scheduled["execution_status"] == "SCHEDULED"
        assert scheduled["reserved_gallons"] == 17, (
            f"ceil(1200 * 1 * 1.10 / 80) = 17 gallons reserved, got {scheduled['reserved_gallons']}"
        )


class TestInsufficientMaterial:
    def test_on_hand_below_required_rejected(self, api):
        """PRD §3.5: "The material lot must be `RECEIVED` or `IN_USE` (else
        `ERR_MATERIAL_LOT_UNAVAILABLE`), must stock the same material the
        quote specified, and its on-hand gallons must cover the reservation
        (else `ERR_INSUFFICIENT_MATERIAL`)."

        Design: Corner/errors/insufficient_material_at_schedule
        """
        ctx = setup_accepted_job(lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St")
        lot = create_material_lot(
            ctx["material"]["id"], delivered_gallons=10, reorder_threshold_gallons=5
        )
        crew = create_crew()
        sheet = create_route_sheet(crew["id"], "2026-08-10")
        post_weather_snapshot("2026-08-10")
        # 900 sqft x 1 coat x 1.10 / 80 = 12.375 -> 13 gallons required; 10 on hand.
        resp = _schedule_attempt(
            api, ctx["work_order"]["id"], sheet["id"], lot["id"], "2026-08-10"
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MATERIAL, 422)

        lot_after = validate_success(api.get_material_lot(lot["id"], DISPATCHER))
        assert lot_after["reserved_gallons"] == 0, "no reservation may persist on failure"
        sheet_after = validate_success(api.get_route_sheet(sheet["id"], DISPATCHER))
        assert sheet_after["booked_sqft"] == 0, "no booking may persist on failure"


class TestResealInterval:
    def test_second_seal_before_interval_rejected(self, api):
        """PRD §3.1: "Its `last_completed_seal_on` records when the most
        recent non-warranty seal job completed, and `next_seal_eligible_on`
        projects when the same property may be sealed again: the completion
        timestamp plus that job's material `reapplication_months`." and "A
        non-warranty seal job scheduled before `next_seal_eligible_on`'s date
        is rejected with `ERR_RESEAL_INTERVAL_NOT_MET`".

        Design: Corner/validations/reseal_interval_gate_on_second_seal
        """
        ctx = setup_completed_job(lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St")
        prop = validate_success(api.get_property(ctx["property"]["id"], ADMIN))
        # completed 2026-08-12T07:00Z + 24 reapplication months
        assert_instant_equal(prop["next_seal_eligible_on"], "2028-08-12T07:00:00Z")

        # New seal quote on the same property (assessment is 11 days old).
        quote2 = create_quote(
            prop["id"], ctx["assessment"]["id"], ctx["material"]["id"],
            include_crack_fill=False, include_patch=False,
        )
        send_quote(quote2["id"])
        accept_quote(quote2["id"], ctx["customer"]["id"])
        wo2 = find_work_order_for_quote(quote2["id"])

        sheet2 = create_route_sheet(ctx["crew"]["id"], "2027-05-03")
        post_weather_snapshot(
            "2027-05-03", min_temp_f=62, max_temp_f=76, precip_probability_pct=10
        )
        resp = _schedule_attempt(
            api, wo2["id"], sheet2["id"], ctx["lot"]["id"], "2027-05-03",
            window_start_hour=8,
        )
        validate_error(resp, ApiErrorId.ERR_RESEAL_INTERVAL_NOT_MET, 422)
        assert get_work_order(wo2["id"])["execution_status"] == "PENDING"


class TestRouteSheetCancel:
    def test_cancel_sheet_with_scheduled_job_rejected(self, api):
        """PRD §3.5: "A route sheet itself may be cancelled from `OPEN`,
        `PUBLISHED`, or `WEATHER_HOLD`, but only while no work order on it
        sits in `SCHEDULED`, `WEATHER_HOLD`, `IN_PROGRESS`, or `CURING` —
        otherwise `ERR_ROUTE_SHEET_NOT_CANCELLABLE`."

        Design: Corner/errors/route_sheet_cancel_with_active_jobs_rejected
        """
        ctx = setup_scheduled_job(lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St")
        resp = api.cancel_route_sheet(ctx["sheet"]["id"], DISPATCHER)
        validate_error(resp, ApiErrorId.ERR_ROUTE_SHEET_NOT_CANCELLABLE, 409)
        sheet = validate_success(api.get_route_sheet(ctx["sheet"]["id"], DISPATCHER))
        assert sheet["status"] == "PUBLISHED"
