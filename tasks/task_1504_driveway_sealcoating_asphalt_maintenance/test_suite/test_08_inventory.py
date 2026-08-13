"""Material lot ledger: conservation across reserve/release/consume,
waste-driven depletion, and quarantine rules."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_accepted_job,
    assert_lot_ledger_conserved,
    assert_material_lot,
    clear_plan_for,
    create_crew,
    create_material,
    create_material_lot,
    create_route_sheet,
    get_material_lot,
    post_weather_snapshot,
    schedule_onto_sheet,
    set_clock,
    setup_accepted_job,
    setup_scheduled_job,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["office_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
CREW_LEAD = TEST_USERS["crew_lead_headers"]

SEAL_ONLY = {"include_crack_fill": False, "include_patch": False}


class TestGallonLedgerInvariant:
    """delivered == reserved + consumed + wasted + on_hand through a reserve,
    a compensated reserve, and a consumption."""

    def _setup_two_jobs_one_lot(self, api):
        ctx = setup_accepted_job(
            address="1 Alpha Way", measured_area_sqft=1200, crack_linear_ft=0,
            pothole_count=0, pothole_area_sqft=0, oil_spot_area_sqft=0,
            quote_overrides=SEAL_ONLY,
        )
        ctx["lot"] = create_material_lot(ctx["material"]["id"])
        ctx["crew"] = create_crew()
        ctx["sheet"] = create_route_sheet(ctx["crew"]["id"], "2026-08-10")
        post_weather_snapshot("2026-08-10")
        sub2 = add_accepted_job(
            ctx, address="2 Beta Way", measured_area_sqft=2000, quote_overrides=SEAL_ONLY
        )
        return ctx, sub2

    def test_ledger_conserved_through_reserve_and_cancel(self, api):
        """PRD §2.9: "The derived `on_hand_gallons` is always the delivered
        quantity minus reserved, consumed, and wasted gallons."

        Design: Difficulty/compensating_invariant/material_lot_gallon_ledger_invariant
        """
        ctx, sub2 = self._setup_two_jobs_one_lot(api)
        job1 = schedule_onto_sheet(
            ctx, {"work_order": ctx["work_order"]}, sheet=ctx["sheet"],
            service_date="2026-08-10", window_start_hour=7, window_end_hour=10,
        )
        lot = get_material_lot(ctx["lot"]["id"])
        assert (lot["reserved_gallons"], lot["consumed_gallons"],
                lot["wasted_gallons"], lot["on_hand_gallons"]) == (17, 0, 0, 83)
        assert_lot_ledger_conserved(lot)

        # 2000 sqft -> ceil(2000 * 1.10 / 80) = 28 gallons, then cancelled.
        job2 = schedule_onto_sheet(
            ctx, sub2, sheet=ctx["sheet"], service_date="2026-08-10",
            window_start_hour=10, window_end_hour=13,
        )
        validate_success(api.cancel_work_order(job2["work_order"]["id"], DISPATCHER))
        lot = get_material_lot(ctx["lot"]["id"])
        assert (lot["reserved_gallons"], lot["consumed_gallons"],
                lot["wasted_gallons"], lot["on_hand_gallons"]) == (17, 0, 0, 83), (
            "the reserve+cancel pair must leave zero drift in the ledger"
        )
        assert_lot_ledger_conserved(lot)
        ctx["job1"] = job1
        return ctx

    def test_ledger_conserved_through_consumption(self, api):
        """PRD §3.7: "the reservation is released in full, `consumed_gallons`
        grows by `gallons_used`, the work order's `reserved_gallons` zeroes,
        and on-hand gallons and the reorder flag recompute."

        Design: Difficulty/compensating_invariant/material_lot_gallon_ledger_invariant
        """
        ctx, sub2 = self._setup_two_jobs_one_lot(api)
        job1 = schedule_onto_sheet(
            ctx, {"work_order": ctx["work_order"]}, sheet=ctx["sheet"],
            service_date="2026-08-10", window_start_hour=7, window_end_hour=10,
        )
        job2 = schedule_onto_sheet(
            ctx, sub2, sheet=ctx["sheet"], service_date="2026-08-10",
            window_start_hour=10, window_end_hour=13,
        )
        validate_success(api.cancel_work_order(job2["work_order"]["id"], DISPATCHER))

        clear_plan_for(job1["work_order"]["id"])
        set_clock("2026-08-10T07:00:00Z")
        validate_success(api.start_work_order(job1["work_order"]["id"], CREW_LEAD))
        finished = validate_success(
            api.finish_work_order(
                job1["work_order"]["id"],
                {
                    "actual_area_sqft": 1200,
                    "actual_crack_ft": 0,
                    "actual_pothole_area_sqft": 0,
                    "actual_stripe_ft": 0,
                    "gallons_used": 15,
                },
                CREW_LEAD,
            )
        )
        assert finished["reserved_gallons"] == 0, "the work order's reservation zeroes"
        lot = get_material_lot(ctx["lot"]["id"])
        assert (lot["reserved_gallons"], lot["consumed_gallons"],
                lot["wasted_gallons"], lot["on_hand_gallons"]) == (0, 15, 0, 85)
        assert_lot_ledger_conserved(lot)


class TestRecordWasteToDepleted:
    def test_waste_equal_to_on_hand_depletes_lot(self, api):
        """PRD §2.9: "A lot reaches `DEPLETED` when on-hand gallons hit zero —
        after a waste recording with no reservations outstanding, or after
        consumption when nothing remains reserved."

        Design: Corner/entities/material_lot_record_waste_to_depleted
        """
        material = create_material()
        lot = create_material_lot(
            material["id"], delivered_gallons=50, reorder_threshold_gallons=5
        )
        assert lot["status"] == "RECEIVED"

        updated = validate_success(
            api.record_waste(lot["id"], {"wasted_gallons": 50}, ADMIN)
        )
        assert_material_lot(updated)
        assert updated["on_hand_gallons"] == 0, "50 delivered - 50 wasted = 0"
        assert updated["status"] == "DEPLETED"


class TestQuarantineInUse:
    def test_quarantine_blocked_while_reserved_then_succeeds(self, api):
        """PRD §2.9: "a lot still holding reservations cannot be quarantined
        and the attempt is rejected with `ERR_MATERIAL_LOT_IN_USE`, while
        referencing a quarantined or depleted lot for new work is rejected
        with `ERR_MATERIAL_LOT_UNAVAILABLE`."

        Design: Corner/errors/material_lot_quarantine_in_use_rejected
        """
        ctx = setup_scheduled_job(
            lot_kind="RESIDENTIAL_DRIVEWAY", address="1 Elm St",
            measured_area_sqft=900, crack_linear_ft=10, pothole_count=1,
            pothole_area_sqft=2, window_start_hour=7, window_end_hour=10,
            drive_minutes_est=15, vehicles_to_move=1,
        )
        lot = get_material_lot(ctx["lot"]["id"])
        assert lot["reserved_gallons"] == 13

        resp = api.quarantine_material_lot(ctx["lot"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_MATERIAL_LOT_IN_USE, 409)

        validate_success(api.cancel_work_order(ctx["work_order"]["id"], DISPATCHER))
        quarantined = validate_success(
            api.quarantine_material_lot(ctx["lot"]["id"], ADMIN)
        )
        assert quarantined["status"] == "QUARANTINED"
