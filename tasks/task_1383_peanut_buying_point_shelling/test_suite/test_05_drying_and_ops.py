"""Dryer bookings (half-open overlap), the ops-run no-show sweep, strikes."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_dryer,
    add_warehouse,
    api_client,
    assert_dryer_booking,
    create_delivery_call_payload,
    create_dryer_booking_payload,
    create_sheller_contract_payload,
    get_buying_point,
    get_grower,
    get_load,
    make_sheller_rep_headers,
    report_load,
    setup_buying_point,
    setup_grower,
    setup_settlement_foundation,
    validate_error,
    validate_success,
    weigh_load,
    grade_load,
    create_active_contract,
    issue_call,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


def _three_drying_loads(grower_id):
    """Three 24.0t loads graded at moisture 11.2 (=> drying REQUIRED)."""
    loads = []
    for _ in range(3):
        load = report_load(grower_id)
        weighed = weigh_load(load["id"], 24.0)
        grade_load(load["id"], weighed["version"], moisture_pct=11.2,
                   foreign_material_pct=3.0, damage_pct=0.0, lsk_pct=0.0)
        loads.append(get_load(load["id"]))
    return loads


class TestDryerBookingOverlap:

    def test_dryer_half_open_adjacency_allowed(self):
        """PRD section 3.6: "Bookings occupy half-open intervals — a new
        booking whose interval from `starts_at` to `ends_at` intersects another
        `BOOKED` booking on the same dryer is rejected with
        `ERR_DRYER_OVERLAP`, while back-to-back adjacency is allowed."
        PRD section 3.6: "the number of cycles is the booking tonnage divided
        by the dryer's `cycle_capacity_tons`, rounded up to a whole cycle, and
        the end is the start plus that many cycles times the dryer's
        `cycle_hours`."

        Design: Difficulty/resource_temporal_overlap/dryer_half_open_adjacency_allowed
        """
        f = setup_settlement_foundation(with_dryer=True)
        loads = _three_drying_loads(f["grower"]["id"])
        dryer_id = f["dryer"]["id"]

        bk1 = validate_success(api_client.create_dryer_booking(
            create_dryer_booking_payload(dryer_id=dryer_id, load_id=loads[0]["id"],
                                         tons=24.0,
                                         starts_at="2026-09-03T06:00:00Z"), ADMIN),
            expected_status=201)
        assert bk1["status"] == "BOOKED"
        # ceil(24/12) = 2 cycles x 6h = 12h from 06:00
        assert bk1["ends_at"].startswith("2026-09-03T18:00:00")

        bk2 = validate_success(api_client.create_dryer_booking(
            create_dryer_booking_payload(dryer_id=dryer_id, load_id=loads[1]["id"],
                                         tons=24.0,
                                         starts_at="2026-09-03T18:00:00Z"), ADMIN),
            expected_status=201)
        assert bk2["status"] == "BOOKED", \
            "start exactly at the prior booking's end is legal adjacency"
        assert bk2["ends_at"].startswith("2026-09-04T06:00:00")

    def test_dryer_overlap_inside_window_rejected(self):
        """PRD section 3.6: "Bookings occupy half-open intervals — a new
        booking whose interval from `starts_at` to `ends_at` intersects another
        `BOOKED` booking on the same dryer is rejected with
        `ERR_DRYER_OVERLAP`, while back-to-back adjacency is allowed."

        Design: Difficulty/resource_temporal_overlap/dryer_half_open_adjacency_allowed
        """
        f = setup_settlement_foundation(with_dryer=True)
        loads = _three_drying_loads(f["grower"]["id"])
        dryer_id = f["dryer"]["id"]

        api_client.create_dryer_booking(
            create_dryer_booking_payload(dryer_id=dryer_id, load_id=loads[0]["id"],
                                         tons=24.0,
                                         starts_at="2026-09-03T06:00:00Z"), ADMIN)
        resp = api_client.create_dryer_booking(
            create_dryer_booking_payload(dryer_id=dryer_id, load_id=loads[2]["id"],
                                         tons=24.0,
                                         starts_at="2026-09-03T17:00:00Z"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_DRYER_OVERLAP)
        assert get_load(loads[2]["id"])["drying_status"] == "REQUIRED"


class TestNoShowSweepCascade:

    def _setup_three_bookings(self):
        f = setup_settlement_foundation(with_dryer=True)
        loads = _three_drying_loads(f["grower"]["id"])
        dryer_id = f["dryer"]["id"]
        starts = ["2026-09-03T06:00:00Z", "2026-09-03T18:00:00Z",
                  "2026-09-04T06:00:00Z"]
        bookings = []
        for load, start in zip(loads, starts):
            bk = validate_success(api_client.create_dryer_booking(
                create_dryer_booking_payload(dryer_id=dryer_id,
                                             load_id=load["id"], tons=24.0,
                                             starts_at=start), ADMIN),
                expected_status=201)
            bookings.append(bk)
        set_clock("2026-09-05T00:00:00Z")
        return f, loads, bookings

    def test_noshow_strikes_suspend_grower_mid_sweep(self):
        """PRD section 3.6: "Every `BOOKED` booking of this buying point whose
        `ends_at` falls strictly before the current logical clock, processed in
        ascending `starts_at` order with ties broken by ascending `created_at`,
        becomes `NO_SHOW`: the load's drying axis returns to `REQUIRED`, and
        the grower's `no_show_strikes` increments by one."
        PRD section 3.6: "When a grower's strikes reach the limit of 2, the
        grower moves `ACTIVE` → `SUSPENDED` and every remaining `BOOKED`
        booking of that grower is cancelled immediately — before those bookings
        are swept — so a mid-sweep suspension cancels later bookings rather
        than no-showing them, and already-cancelled bookings are skipped."

        Design: Difficulty/transitive_cascade/noshow_strike_suspension_cascade
        """
        f, loads, bookings = self._setup_three_bookings()
        api_client.run_ops(f["bp"]["id"], ADMIN)

        b1 = api_client.get_dryer_booking(bookings[0]["id"], ADMIN).json()["data"]
        b2 = api_client.get_dryer_booking(bookings[1]["id"], ADMIN).json()["data"]
        b3 = api_client.get_dryer_booking(bookings[2]["id"], ADMIN).json()["data"]
        assert b1["status"] == "NO_SHOW"
        assert b2["status"] == "NO_SHOW"
        assert b3["status"] == "CANCELLED", \
            "mid-sweep suspension cancels later bookings before they are swept"

        grower = get_grower(f["grower"]["id"])
        assert grower["no_show_strikes"] == 2
        assert grower["status"] == "SUSPENDED"

    def test_noshow_frees_loads_and_bumps_ops_index(self):
        """PRD section 3.6: "Every `BOOKED` booking of this buying point whose
        `ends_at` falls strictly before the current logical clock, processed in
        ascending `starts_at` order with ties broken by ascending `created_at`,
        becomes `NO_SHOW`: the load's drying axis returns to `REQUIRED`, and
        the grower's `no_show_strikes` increments by one."
        PRD section 3.1: "The buying point's `ops_run_index` starts at zero and
        increments only through the operations checkpoint described in §3.6."

        Design: Difficulty/transitive_cascade/noshow_strike_suspension_cascade
        """
        f, loads, bookings = self._setup_three_bookings()
        api_client.run_ops(f["bp"]["id"], ADMIN)

        for load in loads:
            assert get_load(load["id"])["drying_status"] == "REQUIRED", \
                "no-showed / cascade-cancelled bookings free the load to re-book"

        bp_after = get_buying_point(f["bp"]["id"])
        assert bp_after["ops_run_index"] == 1


class TestOpsRunIdempotent:

    def test_ops_run_idempotent_when_nothing_due(self):
        """PRD section 3.8: "Every `ISSUED` or `ALLOCATED` call of this buying
        point whose `dock_window_end` falls strictly before the current logical
        clock, processed in ascending `dock_window_end` order with ties broken
        by ascending `created_at`, becomes `DEFAULTED`".
        PRD section 3.1: "The buying point's `ops_run_index` starts at zero and
        increments only through the operations checkpoint described in §3.6."

        Design: Corner/cross_cutting/ops_run_idempotent_when_nothing_due
        """
        bp = setup_buying_point()  # clock at 2026-09-01T09:00Z
        add_warehouse(bp["id"])
        contract = create_active_contract(bp["id"], total_units_tons=20.0)
        call = issue_call(contract["id"], 10.0)  # dock 2026-09-10, future

        api_client.run_ops(bp["id"], ADMIN)
        api_client.run_ops(bp["id"], ADMIN)

        bp_after = get_buying_point(bp["id"])
        assert bp_after["ops_run_index"] == 2

        call_after = api_client.get_delivery_call(call["id"], ADMIN).json()["data"]
        assert call_after["status"] == "ISSUED", \
            "dock_window_end not strictly before the clock — nothing is due"
        contract_after = api_client.get_sheller_contract(
            contract["id"], ADMIN).json()["data"]
        assert contract_after["default_count"] == 0
        assert contract_after["status"] == "ACTIVE"

    def test_grading_inspector_cannot_create_dryer_returns_forbidden(self):
        """PRD section 4: the dryer creation row lists only `BuyingPointAdmin`.
        PRD section 2.1: "A request whose role is recognized but not permitted
        for the target operation is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/grading_inspector_cannot_create_dryer_returns_forbidden
        """
        bp = setup_buying_point()
        resp = api_client.create_dryer(
            {"buying_point_id": bp["id"], "name": "D1",
             "cycle_capacity_tons": 12, "cycle_hours": 6},
            INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
