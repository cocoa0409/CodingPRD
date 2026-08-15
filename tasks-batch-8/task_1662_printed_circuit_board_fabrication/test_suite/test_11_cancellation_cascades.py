"""Order cancellation: the depth-three cascade, lane-commitment conservation,
and terminal-state lockdown (PRD §3.9).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId,
    assert_lot_conservation,
    create_customer, create_order, create_lane, prepare_order,
    setup_released_order, setup_in_production, release_order,
    get_laminate_lot,
    make_customer_headers,
    TEST_USERS,
    DEFAULT_SHIP_DATE,
)

PLANNER = TEST_USERS["production_planner_headers"]
FAB_ADMIN = TEST_USERS["fab_admin_headers"]
QI = TEST_USERS["quality_inspector_headers"]


def _lane_committed_boards(api, lane_id, ship_date="2026-08-10") -> int:
    data, _ = validate_paginated(
        api.list_lane_slots(lane_id, PLANNER, params={"ship_date": ship_date})
    )
    assert len(data) >= 1, f"expected a slot commitment row for {ship_date}"
    return data[0]["committed_boards"]


class TestCancelCascadeDepth3:
    def test_cancel_released_order_cascade_depth3(self, api):
        """PRD §3.9: "A cancellation fires a depth-three cascade. Link one:
        every panel array of the order in `DRAFT` or `RELEASED` becomes
        `CANCELLED`. Link two, caused by link one: every reservation of a
        just-cancelled array that is still `RESERVED` becomes `RELEASED`. Link
        three, caused by link two: for each released reservation the lot's
        `panels_reserved` decreases by the reservation's `panels_allocated` and
        the lot's `version` advances, and a `DEPLETED` lot whose availability
        rises above zero returns to `QUALIFIED`. ... For a quick-turn order
        that held a lane commitment, the commitment's `committed_boards` is
        reduced by the order's `quantity_boards`."

        Design: Difficulty/transitive_cascade/cancel_released_order_cascade_depth3
        """
        lane = create_lane(lane_code="QT3", turn_days=3)
        ctx = prepare_order(
            company_name="Eta Circuits", contact_email="ops@eta.example",
            credit_limit_cents=100_000_000,
            service_lane="QUICK_TURN", lane=lane,
            lot_code="LOT-C1", panels_total=100, panels_to_reserve=34,
        )
        order = release_order(ctx["order"]["id"])
        assert order["fab_status"] == "RELEASED"
        assert _lane_committed_boards(api, lane["id"]) == 100

        order = get_success_data(
            api.cancel_order(
                ctx["order"]["id"], {"reason": "customer cancelled"},
                make_customer_headers(ctx["customer"]["id"]),
            )
        )
        assert order["fab_status"] == "CANCELLED"

        array = get_success_data(api.get_panel_array(ctx["array"]["id"], PLANNER))
        assert array["status"] == "CANCELLED", "link 1: RELEASED array cancelled"

        reservation = get_success_data(
            api.get_reservation(ctx["reservation"]["id"], PLANNER)
        )
        assert reservation["status"] == "RELEASED", (
            "link 2, caused by link 1: RESERVED reservation released"
        )

        lot = get_laminate_lot(ctx["lot"]["id"])
        assert_lot_conservation(lot)
        assert lot["panels_reserved"] == 0, "link 3, caused by link 2"
        assert lot["panels_consumed"] == 0
        assert lot["panels_available"] == 100
        assert lot["status"] == "QUALIFIED"

        assert _lane_committed_boards(api, lane["id"]) == 0, (
            "the quick-turn lane commitment is released with the order"
        )

    def test_cancel_on_hold_order_keeps_consumed_laminate(self, api):
        """PRD §3.9: "Reservations already `CONSUMED` stay `CONSUMED` — that
        laminate is scrapped with the build." Cancellation is available "only
        while the order is in `QUOTED`, `DFM_REVIEW`, `AWAITING_LAMINATE`,
        `RELEASED`, or `ON_HOLD`".

        Design: Difficulty/transitive_cascade/cancel_released_order_cascade_depth3
        """
        ctx = setup_in_production(
            company_name="Eta Two", contact_email="ops@eta2.example",
            lot_code="LOT-C2",
        )
        order = get_success_data(api.hold_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "ON_HOLD"

        order = get_success_data(
            api.cancel_order(ctx["order"]["id"], {"reason": "scrap the build"}, PLANNER)
        )
        assert order["fab_status"] == "CANCELLED"

        array = get_success_data(api.get_panel_array(ctx["array"]["id"], PLANNER))
        assert array["status"] == "CANCELLED"

        reservation = get_success_data(
            api.get_reservation(ctx["reservation"]["id"], PLANNER)
        )
        assert reservation["status"] == "CONSUMED", (
            "consumed laminate is scrapped with the build, not released"
        )

        lot = get_laminate_lot(ctx["lot"]["id"])
        assert_lot_conservation(lot)
        assert lot["panels_consumed"] == 34
        assert lot["panels_reserved"] == 0
        assert lot["panels_available"] == 66


class TestLaneCommitConservation:
    def test_lane_commit_release_then_cancel_conserves(self, api):
        """PRD §3.6: "A successful release upserts this row, adding the order's
        `quantity_boards` to `committed_boards`". PRD §3.9: "the commitment's
        `committed_boards` is reduced by the order's `quantity_boards`".

        Design: Difficulty/compensating_invariant/lane_commit_release_conservation
        """
        lane = create_lane(lane_code="QT3", turn_days=3)
        ctx = prepare_order(
            company_name="Sigma Circuits", contact_email="ops@sigma.example",
            credit_limit_cents=100_000_000,
            service_lane="QUICK_TURN", lane=lane, quantity_boards=300,
            lot_code="LOT-S1", panels_total=200, panels_to_reserve=100,
        )
        release_order(ctx["order"]["id"])
        assert _lane_committed_boards(api, lane["id"]) == 300

        get_success_data(
            api.cancel_order(ctx["order"]["id"], {"reason": "customer cancelled"},
                             PLANNER)
        )
        assert _lane_committed_boards(api, lane["id"]) == 0, (
            "release + cancel must conserve the lane-day commitment exactly"
        )

    def test_lane_commit_partial_cancel(self, api):
        """PRD §3.6: "A lane's committed boards for a date are the sum of
        `quantity_boards` over the lane's orders whose `requested_ship_date`
        falls on that calendar day and whose `fab_status` is one of `RELEASED`,
        `IN_PRODUCTION`, `ON_HOLD`, `AWAITING_ETEST`, or `COMPLETED`; cancelled
        and shipped orders no longer count."

        Design: Difficulty/compensating_invariant/lane_commit_release_conservation
        """
        lane = create_lane(lane_code="QT3", turn_days=3, capacity_boards_per_day=500)

        ctx_a = prepare_order(
            company_name="Sigma A", contact_email="sa@sigma2.example",
            credit_limit_cents=100_000_000,
            service_lane="QUICK_TURN", lane=lane, quantity_boards=300,
            lot_code="LOT-SA", panels_total=200, panels_to_reserve=100,
        )
        ctx_b = prepare_order(
            company_name="Sigma B", contact_email="sb@sigma2.example",
            credit_limit_cents=100_000_000,
            service_lane="QUICK_TURN", lane=lane, quantity_boards=200,
            lot_code="LOT-SB", panels_total=200, panels_to_reserve=67,
        )
        release_order(ctx_a["order"]["id"])
        release_order(ctx_b["order"]["id"])
        assert _lane_committed_boards(api, lane["id"]) == 500

        get_success_data(
            api.cancel_order(ctx_a["order"]["id"], {"reason": "A cancelled"}, PLANNER)
        )
        assert _lane_committed_boards(api, lane["id"]) == 200, (
            "cancelling the 300-board order leaves only B's 200 committed"
        )
        order_b = get_success_data(api.get_fab_order(ctx_b["order"]["id"], PLANNER))
        assert order_b["fab_status"] == "RELEASED"


class TestCancelGuardAndConsistency:
    def test_cancel_from_cancelled_rejected(self, api):
        """PRD §3.9: cancellation is available "only while the order is in
        `QUOTED`, `DFM_REVIEW`, `AWAITING_LAMINATE`, `RELEASED`, or `ON_HOLD`;
        from `IN_PRODUCTION`, `AWAITING_ETEST`, `COMPLETED`, `SHIPPED`, or
        `CANCELLED` the attempt is rejected with `ERR_ORDER_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_from_cancelled_rejected
        """
        cust = create_customer("Twice Co", "twice@co.example", 5000)
        order = create_order(cust["id"], quantity_boards=10)
        get_success_data(
            api.cancel_order(order["id"], {"reason": "first"},
                             make_customer_headers(cust["id"]))
        )
        resp = api.cancel_order(
            order["id"], {"reason": "second"}, make_customer_headers(cust["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
        order = get_success_data(api.get_fab_order(order["id"], PLANNER))
        assert order["fab_status"] == "CANCELLED"

    def test_immediate_consistency_on_release(self, api):
        """PRD §3.6: "A successful release upserts this row, adding the order's
        `quantity_boards` to `committed_boards`, and moves the order to
        `RELEASED`." PRD §2.2: "operations that create or modify a resource will
        return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_on_release
        """
        lane = create_lane(lane_code="QT3", turn_days=3)
        ctx = prepare_order(
            company_name="Imm Co", contact_email="imm@co.example",
            credit_limit_cents=100_000_000,
            service_lane="QUICK_TURN", lane=lane,
            lot_code="LOT-IM1",
        )
        resp = api.release_order(ctx["order"]["id"], PLANNER)
        body = validate_success(resp, expected_status=200)
        assert body["fab_status"] == "RELEASED", (
            "the release response body already shows the new state"
        )

        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "RELEASED", "the follow-up read agrees"
        assert _lane_committed_boards(api, lane["id"]) == 100
