"""Warehouse staging windows (half-open overlap) and install-crew daily
capacity (aggregate hours)."""
from test_helpers import (
    ApiErrorId,
    api_client,
    approve_signoff,
    create_delivered_delivery,
    create_delivery,
    create_released_kit,
    create_reservation,
    create_signoff,
    dispatch_delivery,
    make_install_crew_lead_headers,
    make_program_manager_headers,
    make_warehouse_lead_headers,
    setup_released_scenario,
    validate_error,
    validate_success,
)

PM = make_program_manager_headers("pm-suite-4")
WL = make_warehouse_lead_headers("wl-suite-4")
ICL = make_install_crew_lead_headers("icl-suite-4")

TEN_AT_1000 = [{"part_number": "PN-400", "quantity": 10,
                "unit_cost_cents": 1000}]


def _released_kit_scenario(name, store_code="STORE-O1", capacity=500):
    return setup_released_scenario(
        program_name=name,
        budget_total_cents=1_000_000,
        fixture_code="WALL-BAY",
        bom_lines=[{"part_number": "PN-400", "quantity": 2,
                    "list_unit_cost_cents": 1000}],
        store_code=store_code,
        config_lines=TEN_AT_1000,
        wave_capacity=capacity,
    )


class TestStagingBayOverlap:

    def test_staging_bay_half_open_overlap(self):
        """PRD §3.5: "A new reservation conflicts with an existing `HELD`
        reservation on the same `staging_bay_code` when the new window's start
        falls before the existing window's end and the existing window's start
        falls before the new window's end; such a conflict is rejected with
        `ERR_STAGING_BAY_OVERLAP`. Windows that merely touch — the new start
        landing exactly on an existing end, or the new end landing exactly on
        an existing start — are adjacent, not overlapping, and are allowed."

        Design: Difficulty/resource_temporal_overlap/staging_bay_half_open_overlap
        """
        ctx = _released_kit_scenario("P-OVL1", capacity=200)
        kit_id = ctx["kit"]["id"]
        res1 = create_reservation(kit_id, "BAY-7", "2026-09-05T10:00:00Z",
                                  "2026-09-05T12:00:00Z")
        assert res1["status"] == "HELD"

        # Adjacent: new start lands exactly on the existing end -> allowed.
        res2 = validate_success(api_client.create_staging_reservation(
            {"kit_id": kit_id, "staging_bay_code": "BAY-7",
             "start_ts": "2026-09-05T12:00:00Z",
             "end_ts": "2026-09-05T14:00:00Z"},
            WL,
        ), expected_status=201)
        assert res2["status"] == "HELD"

        # Straddling the first window -> conflict.
        resp = api_client.create_staging_reservation(
            {"kit_id": kit_id, "staging_bay_code": "BAY-7",
             "start_ts": "2026-09-05T11:00:00Z",
             "end_ts": "2026-09-05T13:00:00Z"},
            WL,
        )
        validate_error(resp, ApiErrorId.ERR_STAGING_BAY_OVERLAP)
        res1_after = validate_success(
            api_client.get_staging_reservation(res1["id"], PM))
        assert res1_after["status"] == "HELD"

    def test_released_reservation_imposes_no_constraint(self):
        """PRD §3.5: "Only `HELD` reservations occupy a bay; windows in
        `CONSUMED`, `RELEASED`, or `EXPIRED` status impose no constraint."

        Design: Difficulty/resource_temporal_overlap/staging_bay_half_open_overlap
        """
        ctx = _released_kit_scenario("P-OVL1B", capacity=200)
        kit_id = ctx["kit"]["id"]
        res1 = create_reservation(kit_id, "BAY-8", "2026-09-05T10:00:00Z",
                                  "2026-09-05T12:00:00Z")
        released = validate_success(
            api_client.release_staging_reservation(res1["id"], WL))
        assert released["status"] == "RELEASED"
        # The same bay may now be re-held over the old window.
        res2 = validate_success(api_client.create_staging_reservation(
            {"kit_id": kit_id, "staging_bay_code": "BAY-8",
             "start_ts": "2026-09-05T11:00:00Z",
             "end_ts": "2026-09-05T13:00:00Z"},
            WL,
        ), expected_status=201)
        assert res2["status"] == "HELD"

    def test_reservation_release_twice_returns_409(self):
        """PRD §3.5: "A lead may voluntarily release a reservation, moving it
        `HELD → RELEASED`; attempting that on a reservation in any other state
        fails with `ERR_RESERVATION_NOT_HELD`."

        Design: Corner/state_machines/reservation_release_twice_returns_409
        """
        ctx = _released_kit_scenario("P-SM7", "STORE-S7", capacity=100)
        reservation = create_reservation(ctx["kit"]["id"], "BAY-2")
        released = validate_success(
            api_client.release_staging_reservation(reservation["id"], WL))
        assert released["status"] == "RELEASED"
        resp = api_client.release_staging_reservation(reservation["id"], WL)
        validate_error(resp, ApiErrorId.ERR_RESERVATION_NOT_HELD)
        after = validate_success(
            api_client.get_staging_reservation(reservation["id"], PM))
        assert after["status"] == "RELEASED"

    def test_delivery_create_consumes_earliest_held_reservation(self):
        """PRD §3.5: "Creating a delivery also resolves the kit's staging: the
        kit's `HELD` reservation with the earliest `start_ts` — ties broken by
        the earliest `created_at` — automatically moves `HELD → CONSUMED`."

        Design: Corner/state_machines/delivery_create_consumes_earliest_held_reservation
        """
        ctx = _released_kit_scenario("P-SM8", "STORE-S8", capacity=100)
        kit_id = ctx["kit"]["id"]
        res_early = create_reservation(kit_id, "BAY-3", "2026-09-05T08:00:00Z",
                                       "2026-09-05T10:00:00Z")
        res_late = create_reservation(kit_id, "BAY-4", "2026-09-06T08:00:00Z",
                                      "2026-09-06T10:00:00Z")
        delivery = create_delivery(kit_id, "CREW-S8", "2026-09-12", 4)
        assert delivery["status"] == "SCHEDULED"
        early_after = validate_success(
            api_client.get_staging_reservation(res_early["id"], PM))
        assert early_after["status"] == "CONSUMED", \
            "the earliest-start_ts HELD reservation must be consumed"
        late_after = validate_success(
            api_client.get_staging_reservation(res_late["id"], PM))
        assert late_after["status"] == "HELD"


class TestCrewDailyCapacity:

    def _three_released_kits(self, name):
        """One program, one capacity-500 COMMITTED wave, three released kits
        of 10 components each."""
        ctx = setup_released_scenario(
            program_name=name,
            budget_total_cents=1_000_000,
            fixture_code="WALL-BAY",
            bom_lines=[{"part_number": "PN-400", "quantity": 2,
                        "list_unit_cost_cents": 1000}],
            store_code="STORE-O2",
            config_lines=TEN_AT_1000,
            wave_capacity=500,
        )
        kits = [ctx["kit"]]
        for store in ("STORE-O3", "STORE-O4"):
            kits.append(create_released_kit(
                ctx["program"]["id"], ctx["prototype"]["id"],
                ctx["wave"]["id"], store, TEN_AT_1000))
        return ctx, kits

    def test_crew_daily_capacity_aggregate_exact_fit_then_reject(self):
        """PRD §3.5: "Crew capacity is enforced as an aggregate per crew per
        calendar date, not as pairwise window overlap: the committed hours for
        a `crew_code` on a `delivery_date` are the sum of
        `estimated_install_hours` over that crew's deliveries on that date in
        `SCHEDULED`, `DISPATCHED`, or `DELIVERED` status, and a new booking is
        rejected with `ERR_CREW_CAPACITY_EXCEEDED` when the committed hours
        plus the new booking's `estimated_install_hours` would exceed eight
        hours — the standard crew day. A booking that brings the crew-day to
        exactly eight hours is allowed."

        Design: Difficulty/resource_temporal_overlap/crew_daily_capacity_aggregate
        """
        _, kits = self._three_released_kits("P-OVL2")
        del1 = create_delivery(kits[0]["id"], "CREW-Z", "2026-09-12", 5)
        assert del1["status"] == "SCHEDULED"
        del2 = create_delivery(kits[1]["id"], "CREW-Z", "2026-09-12", 3)
        assert del2["status"] == "SCHEDULED", "5 + 3 == 8 exactly fills the day"
        resp = api_client.create_install_delivery(
            {"kit_id": kits[2]["id"], "crew_code": "CREW-Z",
             "delivery_date": "2026-09-12", "estimated_install_hours": 1},
            ICL,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED)

    def test_crew_capacity_is_per_crew_per_date(self):
        """PRD §3.5: "Crew capacity is enforced as an aggregate per crew per
        calendar date, not as pairwise window overlap: the committed hours for
        a `crew_code` on a `delivery_date` are the sum of
        `estimated_install_hours` over that crew's deliveries on that date in
        `SCHEDULED`, `DISPATCHED`, or `DELIVERED` status, and a new booking is
        rejected with `ERR_CREW_CAPACITY_EXCEEDED` when the committed hours
        plus the new booking's `estimated_install_hours` would exceed eight
        hours — the standard crew day."

        Design: Difficulty/resource_temporal_overlap/crew_daily_capacity_aggregate
        """
        _, kits = self._three_released_kits("P-OVL2B")
        del1 = create_delivery(kits[0]["id"], "CREW-Z", "2026-09-12", 8)
        assert del1["status"] == "SCHEDULED"
        # A different calendar date is a fresh eight-hour pool for the crew.
        del2 = create_delivery(kits[1]["id"], "CREW-Z", "2026-09-13", 8)
        assert del2["status"] == "SCHEDULED"
        resp = api_client.create_install_delivery(
            {"kit_id": kits[2]["id"], "crew_code": "CREW-Z",
             "delivery_date": "2026-09-12", "estimated_install_hours": 1},
            ICL,
        )
        validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED)

    def test_crew_capacity_excludes_terminal_deliveries(self):
        """PRD §3.5: "`FAILED` and `COMPLETE` deliveries consume no capacity."

        Design: Corner/calculations/crew_capacity_excludes_terminal_deliveries
        """
        ctx, kits = self._three_released_kits("P-CALC3")
        kit1, kit2 = kits[0], kits[1]
        # Drive delivery 1 (8h, CREW-F, 2026-09-12) to COMPLETE via signoff.
        del1 = create_delivered_delivery(kit1["id"], "CREW-F", "2026-09-12", 8)
        signoff = create_signoff(del1["id"],
                                 photo_urls=["https://photos/c3.jpg"])
        approve_signoff(signoff["id"], "sm-1")
        del1_after = validate_success(
            api_client.get_install_delivery(del1["id"], PM))
        assert del1_after["status"] == "COMPLETE"
        # The COMPLETE 8h consumes nothing: a fresh 5h booking fits.
        del2 = create_delivery(kit2["id"], "CREW-F", "2026-09-12", 5)
        assert del2["status"] == "SCHEDULED"


class TestFailRestoresCapacity:

    def test_schedule_fail_crew_hours_conserved(self):
        """PRD §3.5: "A delivery that falls through may be failed from
        `SCHEDULED` or `DISPATCHED` — failing from any other state is likewise
        `ERR_DELIVERY_INVALID_STATE` — moving it to `FAILED`, at which point
        its `estimated_install_hours` stop counting toward crew-day capacity
        and the hours are available for rebooking."

        Design: Difficulty/compensating_invariant/schedule_fail_crew_hours_conserved
        """
        _, kits = TestCrewDailyCapacity._three_released_kits(self, "P-INV2")
        del1 = create_delivery(kits[0]["id"], "CREW-Q", "2026-09-12", 5)
        failed = validate_success(api_client.fail_delivery(del1["id"], ICL))
        assert failed["status"] == "FAILED"
        # The failed 5h no longer counts: 0 + 8 == 8 is allowed.
        del2 = create_delivery(kits[1]["id"], "CREW-Q", "2026-09-12", 8)
        assert del2["status"] == "SCHEDULED"

    def test_dispatched_fail_also_restores_crew_hours(self):
        """PRD §3.5: "A delivery that falls through may be failed from
        `SCHEDULED` or `DISPATCHED` — failing from any other state is likewise
        `ERR_DELIVERY_INVALID_STATE` — moving it to `FAILED`, at which point
        its `estimated_install_hours` stop counting toward crew-day capacity
        and the hours are available for rebooking."

        Design: Difficulty/compensating_invariant/schedule_fail_crew_hours_conserved
        """
        _, kits = TestCrewDailyCapacity._three_released_kits(self, "P-INV2B")
        del1 = create_delivery(kits[0]["id"], "CREW-Q", "2026-09-12", 5)
        dispatch_delivery(del1["id"])
        failed = validate_success(api_client.fail_delivery(del1["id"], ICL))
        assert failed["status"] == "FAILED"
        del2 = create_delivery(kits[1]["id"], "CREW-Q", "2026-09-12", 8)
        assert del2["status"] == "SCHEDULED"
