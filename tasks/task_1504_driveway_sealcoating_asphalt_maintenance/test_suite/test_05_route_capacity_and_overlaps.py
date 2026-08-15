"""Route density gates: capacity equality, drive budget, half-open crew
windows, cure-buffered property access, and the capacity ledger."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_quote,
    add_accepted_job,
    assert_route_sheet,
    assert_sheet_capacity_conserved,
    create_crew,
    create_material_lot,
    create_quote,
    create_route_sheet,
    find_work_order_for_quote,
    get_material_lot,
    get_route_sheet,
    get_work_order,
    post_weather_snapshot,
    schedule_onto_sheet,
    schedule_work_order,
    send_quote,
    setup_accepted_job,
    setup_scheduled_job,
    validate_error,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]

SEAL_ONLY = {"include_crack_fill": False, "include_patch": False}


class TestCapacityEqualityBoundary:
    """Sheet capacity 8000; jobs of 6000, 2000, and 1 sqft."""

    def _setup_three_jobs(self, api):
        ctx = setup_accepted_job(
            address="1 Alpha Way",
            measured_area_sqft=6000,
            crack_linear_ft=0,
            pothole_count=0,
            pothole_area_sqft=0,
            oil_spot_area_sqft=0,
            quote_overrides=SEAL_ONLY,
        )
        ctx["lot"] = create_material_lot(ctx["material"]["id"], delivered_gallons=500)
        ctx["crew"] = create_crew()
        ctx["sheet"] = create_route_sheet(ctx["crew"]["id"], "2026-08-10")
        post_weather_snapshot("2026-08-10")
        sub2 = add_accepted_job(
            ctx, address="2 Beta Way", measured_area_sqft=2000, quote_overrides=SEAL_ONLY
        )
        sub3 = add_accepted_job(
            ctx, address="3 Gamma Way", measured_area_sqft=1, quote_overrides=SEAL_ONLY
        )
        return ctx, sub2, sub3

    def test_exact_capacity_fill_admitted(self, api):
        """PRD §3.5: "Capacity: the sheet's booked square footage plus the
        candidate's `quoted_area_sqft` must not exceed the sheet's
        `capacity_sqft` — equality is allowed — else
        `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/schedule_capacity_equality_boundary
        """
        ctx, sub2, _sub3 = self._setup_three_jobs(api)
        schedule_onto_sheet(
            ctx, {"work_order": ctx["work_order"]}, sheet=ctx["sheet"],
            service_date="2026-08-10", window_start_hour=7, window_end_hour=10,
        )
        result = schedule_onto_sheet(
            ctx, sub2, sheet=ctx["sheet"], service_date="2026-08-10",
            window_start_hour=10, window_end_hour=13,
        )
        assert result["work_order"]["execution_status"] == "SCHEDULED"
        sheet = get_route_sheet(ctx["sheet"]["id"])
        assert sheet["booked_sqft"] == 8000, (
            f"6000 + 2000 must fill the sheet exactly, got {sheet['booked_sqft']}"
        )
        assert sheet["capacity_sqft"] == 8000
        assert sheet["open_capacity_sqft"] == 0
        assert_sheet_capacity_conserved(sheet)

    def test_one_sqft_over_capacity_rejected(self, api):
        """PRD §3.5: "Capacity: the sheet's booked square footage plus the
        candidate's `quoted_area_sqft` must not exceed the sheet's
        `capacity_sqft` — equality is allowed — else
        `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/schedule_capacity_equality_boundary
        """
        ctx, sub2, sub3 = self._setup_three_jobs(api)
        schedule_onto_sheet(
            ctx, {"work_order": ctx["work_order"]}, sheet=ctx["sheet"],
            service_date="2026-08-10", window_start_hour=7, window_end_hour=10,
        )
        schedule_onto_sheet(
            ctx, sub2, sheet=ctx["sheet"], service_date="2026-08-10",
            window_start_hour=10, window_end_hour=13,
        )
        resp = api.schedule_work_order(
            sub3["work_order"]["id"],
            {
                "route_sheet_id": ctx["sheet"]["id"],
                "material_lot_id": ctx["lot"]["id"],
                "scheduled_date": "2026-08-10",
                "window_start_hour": 13,
                "window_end_hour": 14,
                "drive_minutes_est": 10,
                "vehicles_to_move": 0,
            },
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED, 409)
        sheet = get_route_sheet(ctx["sheet"]["id"])
        assert sheet["booked_sqft"] == 8000, "rejected booking must not mutate booked_sqft"

        assert get_work_order(sub3["work_order"]["id"])["execution_status"] == "PENDING"


class TestDriveLimitBoundary:
    def test_drive_budget_equality_then_overflow(self, api):
        """PRD §3.5: "Drive time: the sheet's total drive minutes plus the
        candidate's `drive_minutes_est` must not exceed 180 — equality is
        allowed — else `ERR_ROUTE_DRIVE_LIMIT_EXCEEDED`."

        Design: Corner/validations/route_drive_limit_boundary
        """
        ctx = setup_accepted_job(
            address="1 Alpha Way", measured_area_sqft=100, crack_linear_ft=0,
            pothole_count=0, pothole_area_sqft=0, oil_spot_area_sqft=0,
            quote_overrides=SEAL_ONLY,
        )

        ctx["lot"] = create_material_lot(ctx["material"]["id"])
        ctx["crew"] = create_crew()
        ctx["sheet"] = create_route_sheet(ctx["crew"]["id"], "2026-08-10")
        post_weather_snapshot("2026-08-10")
        sub2 = add_accepted_job(
            ctx, address="2 Beta Way", measured_area_sqft=100, quote_overrides=SEAL_ONLY
        )
        sub3 = add_accepted_job(
            ctx, address="3 Gamma Way", measured_area_sqft=100, quote_overrides=SEAL_ONLY
        )
        schedule_onto_sheet(
            ctx, {"work_order": ctx["work_order"]}, sheet=ctx["sheet"],
            service_date="2026-08-10", window_start_hour=7, window_end_hour=9,
            drive_minutes_est=100,
        )
        second = schedule_onto_sheet(
            ctx, sub2, sheet=ctx["sheet"], service_date="2026-08-10",
            window_start_hour=9, window_end_hour=11, drive_minutes_est=80,
        )
        assert second["work_order"]["execution_status"] == "SCHEDULED", (
            "100 + 80 = 180 minutes exactly exhausts the budget and is admitted"
        )

        resp = api.schedule_work_order(
            sub3["work_order"]["id"],
            {
                "route_sheet_id": ctx["sheet"]["id"],
                "material_lot_id": ctx["lot"]["id"],
                "scheduled_date": "2026-08-10",
                "window_start_hour": 11,
                "window_end_hour": 12,
                "drive_minutes_est": 1,
                "vehicles_to_move": 0,
            },
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_DRIVE_LIMIT_EXCEEDED, 409)
        assert get_work_order(sub3["work_order"]["id"])["execution_status"] == "PENDING"


class TestCrewWindowHalfOpen:
    """Three 100-sqft jobs on one sheet: [7,11), then [11,15), then [10,12)."""

    def _setup_three_jobs(self, api):
        ctx = setup_accepted_job(
            address="1 Alpha Way", measured_area_sqft=100, crack_linear_ft=0,
            pothole_count=0, pothole_area_sqft=0, oil_spot_area_sqft=0,
            quote_overrides=SEAL_ONLY,
        )

        ctx["lot"] = create_material_lot(ctx["material"]["id"])
        ctx["crew"] = create_crew()
        ctx["sheet"] = create_route_sheet(ctx["crew"]["id"], "2026-08-10")
        post_weather_snapshot("2026-08-10")
        sub2 = add_accepted_job(
            ctx, address="2 Beta Way", measured_area_sqft=100, quote_overrides=SEAL_ONLY
        )
        sub3 = add_accepted_job(
            ctx, address="3 Gamma Way", measured_area_sqft=100, quote_overrides=SEAL_ONLY
        )
        schedule_onto_sheet(
            ctx, {"work_order": ctx["work_order"]}, sheet=ctx["sheet"],
            service_date="2026-08-10", window_start_hour=7, window_end_hour=11,
        )
        return ctx, sub2, sub3

    def test_adjacent_half_open_windows_admitted(self, api):
        """PRD §3.5: "Crew window: the half-open interval from
        `window_start_hour` to `window_end_hour` must not overlap any other
        non-cancelled work order's window on the same sheet, else
        `ERR_CREW_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/crew_window_half_open_overlap
        """
        ctx, sub2, _sub3 = self._setup_three_jobs(api)
        result = schedule_onto_sheet(
            ctx, sub2, sheet=ctx["sheet"], service_date="2026-08-10",
            window_start_hour=11, window_end_hour=15,
        )
        assert result["work_order"]["execution_status"] == "SCHEDULED", (
            "[11,15) touches [7,11) at a single endpoint — half-open adjacency is allowed"
        )

    def test_overlapping_window_rejected(self, api):
        """PRD §3.5: "Crew window: the half-open interval from
        `window_start_hour` to `window_end_hour` must not overlap any other
        non-cancelled work order's window on the same sheet, else
        `ERR_CREW_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/crew_window_half_open_overlap
        """
        ctx, sub2, sub3 = self._setup_three_jobs(api)
        schedule_onto_sheet(
            ctx, sub2, sheet=ctx["sheet"], service_date="2026-08-10",
            window_start_hour=11, window_end_hour=15,
        )
        resp = api.schedule_work_order(
            sub3["work_order"]["id"],
            {
                "route_sheet_id": ctx["sheet"]["id"],
                "material_lot_id": ctx["lot"]["id"],
                "scheduled_date": "2026-08-10",
                "window_start_hour": 10,
                "window_end_hour": 12,
                "drive_minutes_est": 15,
                "vehicles_to_move": 0,
            },
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_WINDOW_OVERLAP, 409)

        assert get_work_order(sub3["work_order"]["id"])["execution_status"] == "PENDING"


class TestPropertyAccessCureBuffer:
    """Same property: WO_A blocks 2026-08-10 07:00 through 2026-08-12 11:00
    (window end + 48h forecast cure)."""

    def _setup(self, api):
        ctx = setup_accepted_job(
            address="100 Commerce Way",
            measured_area_sqft=500,
            crack_linear_ft=0,
            pothole_count=0,
            pothole_area_sqft=0,
            oil_spot_area_sqft=0,
            quote_overrides=SEAL_ONLY,
        )

        ctx["lot"] = create_material_lot(ctx["material"]["id"], delivered_gallons=200)
        ctx["crew"] = create_crew()
        sheet1 = create_route_sheet(ctx["crew"]["id"], "2026-08-10")
        sheet2 = create_route_sheet(ctx["crew"]["id"], "2026-08-11")
        sheet3 = create_route_sheet(ctx["crew"]["id"], "2026-08-12")
        for day in ("2026-08-10", "2026-08-11", "2026-08-12"):
            post_weather_snapshot(day)
        # WO_A scheduled on 08-10 [7,11)
        schedule_onto_sheet(
            ctx, {"work_order": ctx["work_order"]}, sheet=sheet1,
            service_date="2026-08-10", window_start_hour=7, window_end_hour=11,
            vehicles_to_move=2,
        )
        # Second job on the SAME property (crack-only), accepted after the first.

        quote2 = create_quote(
            ctx["property"]["id"], ctx["assessment"]["id"], ctx["material"]["id"],
            include_seal=False, include_patch=False,
        )
        send_quote(quote2["id"])
        accept_quote(quote2["id"], ctx["customer"]["id"])
        wo2 = find_work_order_for_quote(quote2["id"])
        ctx.update({"sheet2": sheet2, "sheet3": sheet3, "wo2": wo2})
        return ctx

    def test_overlap_with_buffered_block_rejected(self, api):
        """PRD §3.5: "Property access: the cure-buffered blocked interval for
        this job — from the scheduled date at `window_start_hour` through the
        provisional access-block end described below — must not overlap any
        other non-cancelled work order's blocked interval on the same
        property, else `ERR_ACCESS_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/property_access_cure_buffer_overlap
        """
        ctx = self._setup(api)
        resp = api.schedule_work_order(
            ctx["wo2"]["id"],
            {
                "route_sheet_id": ctx["sheet2"]["id"],
                "material_lot_id": ctx["lot"]["id"],
                "scheduled_date": "2026-08-11",
                "window_start_hour": 7,
                "window_end_hour": 9,
                "drive_minutes_est": 15,
                "vehicles_to_move": 1,
            },
            DISPATCHER,
        )
        # WO_A blocks the property until 2026-08-12T11:00Z (11:00 + 48h cure).
        validate_error(resp, ApiErrorId.ERR_ACCESS_WINDOW_OVERLAP, 409)

        assert get_work_order(ctx["wo2"]["id"])["execution_status"] == "PENDING", (
            "a rejected schedule leaves no partial booking"
        )

    def test_start_after_buffered_end_admitted(self, api):
        """PRD §3.5: "Property access: the cure-buffered blocked interval for
        this job — from the scheduled date at `window_start_hour` through the
        provisional access-block end described below — must not overlap any
        other non-cancelled work order's blocked interval on the same
        property, else `ERR_ACCESS_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/property_access_cure_buffer_overlap
        """
        ctx = self._setup(api)
        resp = api.schedule_work_order(
            ctx["wo2"]["id"],
            {
                "route_sheet_id": ctx["sheet2"]["id"],
                "material_lot_id": ctx["lot"]["id"],
                "scheduled_date": "2026-08-11",
                "window_start_hour": 7,
                "window_end_hour": 9,
                "drive_minutes_est": 15,
                "vehicles_to_move": 1,
            },
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_ACCESS_WINDOW_OVERLAP, 409)

        scheduled = schedule_work_order(
            ctx["wo2"]["id"],
            ctx["sheet3"]["id"],
            ctx["lot"]["id"],
            "2026-08-12",
            window_start_hour=12,
            window_end_hour=14,
            drive_minutes_est=15,
            vehicles_to_move=1,
        )
        assert scheduled["execution_status"] == "SCHEDULED", (
            "2026-08-12T12:00Z starts after the buffered end 2026-08-12T11:00Z"
        )


class TestCapacityLedgerInvariant:
    def _setup_two_jobs(self, api):
        ctx = setup_accepted_job(
            address="1 Alpha Way", measured_area_sqft=6000, crack_linear_ft=0,
            pothole_count=0, pothole_area_sqft=0, oil_spot_area_sqft=0,
            quote_overrides=SEAL_ONLY,
        )

        ctx["lot"] = create_material_lot(ctx["material"]["id"], delivered_gallons=500)
        ctx["crew"] = create_crew()
        ctx["sheet"] = create_route_sheet(ctx["crew"]["id"], "2026-08-10")
        post_weather_snapshot("2026-08-10")
        sub2 = add_accepted_job(
            ctx, address="2 Beta Way", measured_area_sqft=2000, quote_overrides=SEAL_ONLY
        )
        return ctx, sub2

    def test_capacity_conserved_through_schedule(self, api):
        """PRD §2.10: "The derived `open_capacity_sqft` is capacity minus
        booked area, recomputed on every mutation."

        Design: Difficulty/compensating_invariant/route_sheet_capacity_ledger_invariant
        """
        ctx, sub2 = self._setup_two_jobs(api)
        schedule_onto_sheet(
            ctx, {"work_order": ctx["work_order"]}, sheet=ctx["sheet"],
            service_date="2026-08-10", window_start_hour=7, window_end_hour=10,
        )
        schedule_onto_sheet(
            ctx, sub2, sheet=ctx["sheet"], service_date="2026-08-10",
            window_start_hour=10, window_end_hour=13,
        )
        sheet = get_route_sheet(ctx["sheet"]["id"])
        assert_route_sheet(sheet)
        assert sheet["capacity_sqft"] == 8000
        assert sheet["booked_sqft"] == 8000
        assert sheet["open_capacity_sqft"] == 0
        assert_sheet_capacity_conserved(sheet)

    def test_capacity_conserved_through_cancel(self, api):
        """PRD §3.5: "Cancelling a work order — allowed from `PENDING`,
        `SCHEDULED`, or `WEATHER_HOLD`, else `ERR_WORK_ORDER_NOT_CANCELLABLE`
        — runs the mirror-image compensation: the sheet's booking releases and
        its open capacity recomputes".

        Design: Difficulty/compensating_invariant/route_sheet_capacity_ledger_invariant
        """
        ctx, sub2 = self._setup_two_jobs(api)
        schedule_onto_sheet(
            ctx, {"work_order": ctx["work_order"]}, sheet=ctx["sheet"],
            service_date="2026-08-10", window_start_hour=7, window_end_hour=10,
        )
        schedule_onto_sheet(
            ctx, sub2, sheet=ctx["sheet"], service_date="2026-08-10",
            window_start_hour=10, window_end_hour=13,
        )
        validate_success(api.cancel_work_order(ctx["work_order"]["id"], DISPATCHER))
        sheet = get_route_sheet(ctx["sheet"]["id"])
        assert sheet["capacity_sqft"] == 8000, "capacity itself never mutates"
        assert sheet["booked_sqft"] == 2000
        assert sheet["open_capacity_sqft"] == 6000
        assert_sheet_capacity_conserved(sheet)


class TestGallonsRequiredCeiling:
    def test_two_coat_reservation_rounds_up_to_whole_gallons(self, api):
        """PRD §3.5: "Otherwise the gallons required are the area times the
        coat count times a waste factor of 1.10, divided by the material's
        `coverage_sqft_per_gallon`, rounded up to whole gallons — the same
        formula feeds both the quote cost floor and the lot reservation." PRD
        §3.5: "The lot's `reserved_gallons` grows by that amount, a first
        reservation flips the lot from `RECEIVED` to `IN_USE`, and the lot's
        on-hand gallons and `reorder_flag` recompute."

        Design: Corner/calculations/gallons_required_ceil_two_coats
        """
        ctx = setup_scheduled_job(
            measured_area_sqft=1200,
            crack_linear_ft=0,
            pothole_count=0,
            pothole_area_sqft=0,
            oil_spot_area_sqft=0,
            quote_overrides={**SEAL_ONLY, "coats": 2},
            delivered_gallons=200,
            window_start_hour=7,
            window_end_hour=11,
            drive_minutes_est=15,
            vehicles_to_move=2,
        )
        # ceil(1200 * 2 * 1.10 / 80) = ceil(33.0) = 33
        assert ctx["work_order"]["reserved_gallons"] == 33, (
            f"1200 sqft x 2 coats x 1.10 / 80 rounds up to 33, got "
            f"{ctx['work_order']['reserved_gallons']}"
        )
        lot = get_material_lot(ctx["lot"]["id"])
        assert lot["reserved_gallons"] == 33
        assert lot["on_hand_gallons"] == 167
        assert lot["status"] == "IN_USE"


class TestRouteSheetCapacityDefault:
    def test_capacity_defaults_to_crew_daily_capacity(self, api):
        """PRD §3.5: "The sheet's `capacity_sqft` defaults to the crew's
        `daily_capacity_sqft` when omitted."

        Design: Corner/entities/route_sheet_capacity_defaults_to_crew_capacity
        """
        crew = create_crew(daily_capacity_sqft=8000)
        defaulted = validate_success(
            api.create_route_sheet(
                {"crew_id": crew["id"], "service_date": "2026-08-10"}, DISPATCHER
            ),
            201,
        )
        assert defaulted["capacity_sqft"] == 8000, (
            f"omitted capacity copies the crew default 8000, got {defaulted['capacity_sqft']}"
        )
        overridden = validate_success(
            api.create_route_sheet(
                {"crew_id": crew["id"], "service_date": "2026-08-11", "capacity_sqft": 6000},
                DISPATCHER,
            ),
            201,
        )
        assert overridden["capacity_sqft"] == 6000
