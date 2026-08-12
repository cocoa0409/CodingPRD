"""Order holds: shortage recovery, manual release, and cancel cascades."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_box_line,
    add_door_line,
    assign_line_to_batch,
    assign_order_to_route,
    create_assembly_line,
    create_dealer,
    create_door_style,
    create_draft_order,
    create_finish,
    create_mixing_batch,
    create_route,
    create_sub_lot_payload,
    get_success_data,
    make_dealer_headers,
    setup_shipped_door_order,
    setup_shortage_hold_environment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
FINISH = TEST_USERS["finish_supervisor_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
SHIPPING = TEST_USERS["shipping_coordinator_headers"]


class TestReceiptRecovery:
    def test_receipt_recovers_overdraft_releases_hold(self, api):
        """PRD §3.5: "Posting a receipt of `qty` units against a component
        increases `on_hand_qty` by that amount, recomputes `available_qty`, and
        increments the component's `version`. When the recomputed available
        quantity is zero or greater, every `PLACED` `COMPONENT_SHORTAGE` hold
        referencing that component releases automatically; each affected order's
        `hold_status` is recomputed, and any pending auto-transitions fire."

        Design: Corner/cross_cutting_layers/receipt_recovers_overdraft_releases_hold
        """
        env = setup_shortage_hold_environment(on_hand_qty=0, line_qty=50, line_width=30, line_height=20)
        assert env["hold"] is not None and env["hold"]["status"] == "PLACED"
        # area 30,000 -> sheets 8 -> available -8; a receipt of 10 lifts it to 2.
        comp = validate_success(
            api.receive_component(env["component"]["id"], {"qty": 10}, PLANNER)
        )
        assert comp["on_hand_qty"] == 10
        assert comp["reserved_qty"] == 8
        assert comp["available_qty"] == 2
        holds, _meta = validate_paginated(api.list_order_holds(env["order"]["id"], PLANNER))
        assert holds[0]["status"] == "RELEASED", "recovery to >= 0 must auto-release the hold"
        order = validate_success(api.get_order(env["order"]["id"], PLANNER))
        assert order["hold_status"] == "NONE"

    def test_release_already_released_hold_rejected(self, api):
        """PRD §3.7: "A shortage hold releases automatically when a receipt lifts
        the component's `available_qty` back to zero or greater."
        PRD §3.7: "And a `PlantAdmin` may release any `PLACED` hold manually as an
        override; releasing a hold that is not `PLACED` is rejected with
        `ERR_HOLD_NOT_RELEASABLE` (HTTP 409)."

        Design: Corner/state_machines/release_already_released_hold_rejected
        """
        env = setup_shortage_hold_environment(on_hand_qty=0, line_qty=50, line_width=30, line_height=20)
        hold = env["hold"]
        assert hold is not None and hold["status"] == "PLACED"
        # sheets required 8; a receipt of exactly 8 returns available to 0.
        get_success_data(api.receive_component(env["component"]["id"], {"qty": 8}, PLANNER))
        comp = validate_success(api.get_component(env["component"]["id"], PLANNER))
        assert comp["available_qty"] == 0
        resp = api.release_order_hold(hold["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_HOLD_NOT_RELEASABLE)


class TestCancelCascade:
    def _submitted_order_in_partial_production(self, api):
        dealer = create_dealer(price_level="L2")
        style = create_door_style(construction="SHAKER", base_list_price_cents=30000)
        finish = create_finish(upcharge_pct=0.10, finish_code="FS-SAT-10",
                               color_name="Oak Satin", sheen="SATIN")
        order = create_draft_order(dealer)
        door_line = add_door_line(order, style, finish, qty=4, unit_price=30000)
        box_line = add_box_line(order, finish, qty=6, unit_price=50000)
        get_success_data(api.submit_order(order["id"], make_dealer_headers(dealer["id"])))
        batch = create_mixing_batch(finish, capacity_doors=10, sheen_lot_no="LOT-1")
        assign_line_to_batch(batch, door_line)
        assembly_line = create_assembly_line(line_code="AL-1")
        # Deliberately partial coverage (5 of 6) so the order stays SUBMITTED
        # and therefore cancellable.
        sub_lot = get_success_data(
            api.create_sub_lot(
                create_sub_lot_payload(
                    box_line["id"], assembly_line["id"],
                    scheduled_date="2026-05-03", start_minute=60, qty=5,
                ),
                PLANNER,
            )
        )
        route = create_route(route_code="RT-C", route_date="2026-05-06", capacity_cu_ft=500.0)
        assignment = assign_order_to_route(route, order)
        return {
            "dealer": dealer, "order": assignment["order"], "door_line": door_line,
            "box_line": box_line, "batch": batch, "sub_lot": sub_lot,
            "route": route, "route_after_assign": assignment["route"],
        }

    def test_order_cancel_full_compensation_cascade(self, api):
        """PRD §3.7: "Cancelling a `SUBMITTED` order does all of that and more:
        each door line's `finish_batch_id` is cleared and every affected batch
        recomputes its `assigned_door_count`; every `SCHEDULED` sub-lot covering
        its box lines moves to `CANCELLED`, which frees the assembly line's window
        and day load and recomputes each covered line's `slotted_qty` to exclude
        the cancelled sub-lots; every `PLACED` hold on the order releases; and if
        the order sat on a delivery route, it is removed — the route's
        `reserved_cu_ft` decreases by the order's `cube_ft`, the route's
        `assigned_order_count` decreases by one, and the order's
        `delivery_route_id` returns to null."

        Design: Corner/state_machines/order_cancel_full_compensation_cascade
        """
        env = self._submitted_order_in_partial_production(api)
        # door cube 15x30x1x4/1728 = 1.04; box cube 24x30x12x6/1728 = 30.0.
        assert env["route_after_assign"]["reserved_cu_ft"] == pytest.approx(31.04)
        cancelled = validate_success(
            api.cancel_order(env["order"]["id"], make_dealer_headers(env["dealer"]["id"]))
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["delivery_route_id"] is None
        batch = validate_success(api.get_finish_batch(env["batch"]["id"], ADMIN))
        assert batch["assigned_door_count"] == 0, "the batch assignment must be compensated"
        sub_lot = validate_success(api.get_sub_lot(env["sub_lot"]["id"], ADMIN))
        assert sub_lot["status"] == "CANCELLED"
        rows, _meta = validate_paginated(api.list_delivery_routes(SHIPPING, params={"status": "PLANNED"}))
        route = [r for r in rows if r["id"] == env["route"]["id"]][0]
        assert route["reserved_cu_ft"] == pytest.approx(0.0)
        assert route["assigned_order_count"] == 0

    def test_cancel_shipped_order_rejected_terminal_lockdown(self, api, plant_admin_headers):
        """PRD §3.7: "cancellation from any state other than `DRAFT` or `SUBMITTED`
        is rejected with `ERR_ORDER_NOT_CANCELLABLE` (HTTP 409), and the acting
        dealer must own the order."
        PRD §3.7: "Once an order has reached `IN_PRODUCTION` it can no longer be
        cancelled at all."

        Design: Corner/state_machines/cancel_shipped_order_rejected_terminal_lockdown
        """
        env = setup_shipped_door_order(price_level="L4", qty=4, unit_price=30000, upcharge_pct=0.10)
        resp = api.cancel_order(env["order"]["id"], make_dealer_headers(env["dealer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)
        line = validate_success(api.get_order_line(env["line"]["id"], plant_admin_headers))
        assert line["status"] == "SHIPPED", "no compensation cascade may fire for a shipped order"
