"""The release guard chain, quick-turn lane per-day capacity, and lane
commitment bookkeeping (PRD §3.6).

Lane-capacity tests use a 100,000,000-cent credit limit so the credit gate
(PRD §3.6, evaluated after the capacity gate) cannot interfere.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    create_customer, create_order, create_lane, prepare_order, release_order,
    reserve_panels, create_and_lock_stackup, submit_dfm, dfm_approve,
    create_and_release_array, create_drill_program, submit_drill_program,
    approve_drill_program, create_qualified_lot,
    make_customer_headers,
    TEST_USERS,
    DEFAULT_SHIP_DATE,
)

PLANNER = TEST_USERS["production_planner_headers"]
CAM = TEST_USERS["cam_operator_headers"]


def _prepare_qt_order(lane_id, *, qty, ship_date, lot_code,
                      panels_to_reserve=34, credit=100_000_000, **kw):
    # Company/contact-email must be unique per call; derive from lot_code,
    # which every caller already keeps distinct.
    return prepare_order(
        contact_email=kw.pop("contact_email", None),
        company_name=kw.pop("company_name", f"QT {lot_code}"),
        credit_limit_cents=credit,
        service_lane="QUICK_TURN",
        lane={"id": lane_id},
        quantity_boards=qty,
        requested_ship_date=ship_date,
        lot_code=lot_code,
        panels_to_reserve=panels_to_reserve,
        **kw,
    )


def _lane_committed_boards(api, lane_id, ship_date="2026-08-10") -> int:
    data, meta = validate_paginated(
        api.list_lane_slots(lane_id, PLANNER, params={"ship_date": ship_date})
    )
    assert len(data) >= 1, f"expected a slot commitment row for {ship_date}"
    return data[0]["committed_boards"]


class TestReleaseStateGuard:
    def test_release_from_dfm_review_rejected_invalid_state(self, api):
        """PRD §3.6: release is "performed by a `ProductionPlanner` on an order
        in `AWAITING_LAMINATE`" and "A generic `ERR_INVALID_STATE` guards the
        transition itself ahead of all of these." — including ahead of the
        laminate-coverage fiscal check, which an array-less DFM_REVIEW order
        would also fail.

        Design: Difficulty/priority_pair_validation_conflict/release_state_beats_insufficient_laminate
        """
        ctx = prepare_order(
            company_name="Iota Circuits", contact_email="ops@iota.example",
            advance_to="DFM_REVIEW", with_array=False, with_drill=False,
            with_lot=False, with_reservation=False,
        )
        assert ctx["order"]["fab_status"] == "DFM_REVIEW"
        resp = api.release_order(ctx["order"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_release_from_quoted_rejected_invalid_state(self, api):
        """PRD §3.6: release is "performed by a `ProductionPlanner` on an order
        in `AWAITING_LAMINATE`" and "A generic `ERR_INVALID_STATE` guards the
        transition itself ahead of all of these."

        Design: Difficulty/priority_pair_validation_conflict/release_state_beats_insufficient_laminate
        """
        cust = create_customer("Iota Two", "ops@iota2.example", 1_000_000)
        order = create_order(cust["id"])
        assert order["fab_status"] == "QUOTED"
        resp = api.release_order(order["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestReleaseDrillGate:
    def test_release_rejected_while_drill_under_review_then_succeeds(self, api):
        """PRD §3.6: "the order's latest drill program by `revision` must be
        `APPROVED` (`ERR_DRILL_NOT_APPROVED`)" — the first guard of the release
        chain.

        Design: Difficulty/cross_entity_state_dependency/release_requires_drill_approved
        """
        ctx = prepare_order(
            company_name="Nu Circuits", contact_email="ops@nu.example",
            lot_code="LOT-N1", with_drill=False,
        )
        # Drill program exists but sits in UNDER_REVIEW.
        program = create_drill_program(ctx["order"]["id"])
        submit_drill_program(program["id"])

        resp = api.release_order(ctx["order"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_DRILL_NOT_APPROVED)

        approve_drill_program(program["id"])
        order = release_order(ctx["order"]["id"])
        assert order["fab_status"] == "RELEASED", (
            "once the drill program reaches APPROVED the release must succeed"
        )

    def test_release_without_any_drill_program_rejected(self, api):
        """PRD §3.6: "the order's latest drill program by `revision` must be
        `APPROVED` (`ERR_DRILL_NOT_APPROVED`)" — with no drill program at all
        there is no APPROVED latest program, so the same guard fires.

        Design: Difficulty/cross_entity_state_dependency/release_requires_drill_approved
        """
        ctx = prepare_order(
            company_name="Nu Two", contact_email="ops@nu2.example",
            lot_code="LOT-N2", with_drill=False,
        )
        resp = api.release_order(ctx["order"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_DRILL_NOT_APPROVED)


class TestLaneCapacityExactFit:
    def test_lane_capacity_exact_fit_then_one_over(self, api):
        """PRD §3.6: "the committed boards for the lane on the requested ship
        date plus the order's `quantity_boards` must not exceed the lane's
        `capacity_boards_per_day`, with equality allowed, else
        `ERR_LANE_CAPACITY_EXCEEDED`".

        Design: Difficulty/boundary_precision_check/lane_capacity_exact_fit
        """
        lane = create_lane(lane_code="QT3", turn_days=3, capacity_boards_per_day=500)
        cust = create_customer("Mu Circuits", "ops@mu.example", 100_000_000)
        lot = create_qualified_lot("LOT-L1", panels_total=500)

        o1 = _prepare_qt_order(lane["id"], qty=300,
                               ship_date=DEFAULT_SHIP_DATE, lot_code="LOT-L1-O1",
                               with_lot=False, with_reservation=False)
        reserve_panels(o1["order"]["id"], o1["array"]["id"], lot["id"], 100)
        o2 = _prepare_qt_order(lane["id"], qty=200,
                               ship_date=DEFAULT_SHIP_DATE, lot_code="LOT-L1-O2",
                               with_lot=False, with_reservation=False)
        reserve_panels(o2["order"]["id"], o2["array"]["id"], lot["id"], 67)
        o3 = _prepare_qt_order(lane["id"], qty=1,
                               ship_date=DEFAULT_SHIP_DATE, lot_code="LOT-L1-O3",
                               with_lot=False, with_reservation=False)
        reserve_panels(o3["order"]["id"], o3["array"]["id"], lot["id"], 1)

        r1 = release_order(o1["order"]["id"])
        assert r1["fab_status"] == "RELEASED"
        r2 = release_order(o2["order"]["id"])
        assert r2["fab_status"] == "RELEASED", (
            "300 + 200 == 500 == capacity: the inclusive boundary must pass"
        )
        assert _lane_committed_boards(api, lane["id"]) == 500

        resp = api.release_order(o3["order"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_LANE_CAPACITY_EXCEEDED)

    def test_single_order_at_full_capacity_passes(self, api):
        """PRD §3.6: "must not exceed the lane's `capacity_boards_per_day`, with
        equality allowed" — a single order whose quantity equals the daily
        capacity releases, and "A successful release upserts this row, adding
        the order's `quantity_boards` to `committed_boards`".

        Design: Difficulty/boundary_precision_check/lane_capacity_exact_fit
        """
        lane = create_lane(lane_code="QT3", turn_days=3, capacity_boards_per_day=500)
        cust = create_customer("Mu Two", "ops@mu2.example", 100_000_000)
        # qty 500 -> panels_required = ceil(500/3) = 167.
        ctx = _prepare_qt_order(lane["id"], qty=500,
                                ship_date=DEFAULT_SHIP_DATE, lot_code="LOT-L5",
                                panels_total=500, panels_to_reserve=167)
        order = release_order(ctx["order"]["id"])
        assert order["fab_status"] == "RELEASED"
        assert _lane_committed_boards(api, lane["id"]) == 500


class TestLaneDayAggregateCapacity:
    def test_capacity_is_per_day_not_cross_day(self, api):
        """PRD §3.6: "A lane's committed boards for a date are the sum of
        `quantity_boards` over the lane's orders whose `requested_ship_date`
        falls on that calendar day and whose `fab_status` is one of `RELEASED`,
        `IN_PRODUCTION`, `ON_HOLD`, `AWAITING_ETEST`, or `COMPLETED`; cancelled
        and shipped orders no longer count."

        Design: Difficulty/resource_temporal_overlap/lane_day_aggregate_capacity
        """
        lane = create_lane(lane_code="QT3", turn_days=3, capacity_boards_per_day=500)
        cust = create_customer("Omicron Circuits", "ops@omicron.example", 100_000_000)
        lot = create_qualified_lot("LOT-O1", panels_total=500)

        # Saturate 2026-08-10 with a qty-500 order.
        o1 = _prepare_qt_order(lane["id"], qty=500,
                               ship_date="2026-08-10T00:00:00Z",
                               lot_code="X1", with_lot=False, with_reservation=False)
        reserve_panels(o1["order"]["id"], o1["array"]["id"], lot["id"], 167)
        release_order(o1["order"]["id"])
        assert _lane_committed_boards(api, lane["id"], "2026-08-10") == 500

        # The next calendar day is a separate aggregate: a second qty-500 order
        # shipping 2026-08-11 releases even though 2026-08-10 is saturated.
        o2 = _prepare_qt_order(lane["id"], qty=500,
                               ship_date="2026-08-11T00:00:00Z",
                               lot_code="X2", with_lot=False, with_reservation=False)
        reserve_panels(o2["order"]["id"], o2["array"]["id"], lot["id"], 167)
        r2 = release_order(o2["order"]["id"])
        assert r2["fab_status"] == "RELEASED", (
            "per-day aggregate semantics: 2026-08-11 is independent of 2026-08-10"
        )
        assert _lane_committed_boards(api, lane["id"], "2026-08-11") == 500

        # One more board on the saturated day overflows.
        o3 = _prepare_qt_order(lane["id"], qty=1,
                               ship_date="2026-08-10T00:00:00Z",
                               lot_code="X3", with_lot=False, with_reservation=False)
        reserve_panels(o3["order"]["id"], o3["array"]["id"], lot["id"], 1)
        resp = api.release_order(o3["order"]["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_LANE_CAPACITY_EXCEEDED)

    def test_cancelled_orders_free_lane_capacity(self, api):
        """PRD §3.6: "cancelled and shipped orders no longer count" and PRD
        §3.9: "For a quick-turn order that held a lane commitment, the
        commitment's `committed_boards` is reduced by the order's
        `quantity_boards`."

        Design: Difficulty/resource_temporal_overlap/lane_day_aggregate_capacity
        """
        lane = create_lane(lane_code="QT3", turn_days=3, capacity_boards_per_day=500)
        cust = create_customer("Omicron Two", "ops@omicron2.example", 100_000_000)

        o1 = _prepare_qt_order(lane["id"], qty=500,
                               ship_date=DEFAULT_SHIP_DATE, lot_code="LOT-OC1",
                               panels_total=500, panels_to_reserve=167)
        release_order(o1["order"]["id"])
        assert _lane_committed_boards(api, lane["id"]) == 500

        get_success_data(api.cancel_order(o1["order"]["id"], {"reason": "cancel"}, PLANNER))
        assert _lane_committed_boards(api, lane["id"]) == 0, (
            "the cancelled order's 500 boards must leave the day aggregate"
        )

        # The freed day accepts a fresh full-capacity order.
        o2 = _prepare_qt_order(lane["id"], qty=500,
                               ship_date=DEFAULT_SHIP_DATE, lot_code="LOT-OC2",
                               panels_total=500, panels_to_reserve=167)
        r2 = release_order(o2["order"]["id"])
        assert r2["fab_status"] == "RELEASED"
