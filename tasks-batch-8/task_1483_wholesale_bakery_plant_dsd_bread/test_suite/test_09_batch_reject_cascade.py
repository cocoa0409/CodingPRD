"""Batch-reject depth-3 cascade: plan shortfall -> stop flag -> order SHORTED
(PRD §3.4, §2.6)."""
from test_helpers import (
    TEST_USERS,
    create_route,
    create_stop,
    make_qa_headers,
    setup_released_batch_scenario,
    validate_success,
)


def _rejection_ctx():
    """Stop PENDING on a PLANNED route with batch A assigned; batch A is
    RELEASED. Triggering reject on the batch fires the three-hop cascade."""
    ctx = setup_released_batch_scenario(plant_name="Plant Iota", order_qty=100)
    plant = ctx["plant"]
    driver = ctx["driver"]
    order = ctx["order"]
    batch = ctx["batch"]

    route = create_route(plant["id"], driver["id"])
    stop = create_stop(route["id"], order["id"], 100, [batch["id"]])
    ctx.update({"route": route, "stop": stop})
    return ctx


class TestBatchRejectCascadePlanStopOrder:
    def test_reject_sets_batch_terminal(self, api):
        """PRD §3.4: "all six rejections land in the terminal `REJECTED` state
        and fire the same three-hop cascade."

        Design: Difficulty/transitive_cascade/batch_reject_cascade_plan_stop_order
        """
        ctx = _rejection_ctx()
        batch = ctx["batch"]
        rejected = validate_success(
            api.reject_batch(
                batch["id"], {"reason": "metal detector alarm"}, make_qa_headers("qa-1")
            )
        )
        assert rejected["status"] == "REJECTED"

    def test_reject_cascades_plan_stop_order(self, api):
        """PRD §3.4: "Hop one adds the batch's `qty_units` to the plan's
        `shortfall_units` and increments the plan's `version`. Hop two sets
        `shortfall_flag` to true on every `PENDING` route stop whose
        `batch_ids` contain this batch. Hop three moves the store order
        behind each flagged stop from `LOCKED` to `SHORTED`, incrementing
        each such order's `version`."

        Design: Difficulty/transitive_cascade/batch_reject_cascade_plan_stop_order
        """
        ctx = _rejection_ctx()
        batch = ctx["batch"]
        plan = ctx["plan"]
        stop = ctx["stop"]
        order = ctx["order"]

        validate_success(
            api.reject_batch(
                batch["id"], {"reason": "metal detector alarm"}, make_qa_headers("qa-1")
            )
        )

        plan_after = validate_success(
            api.get_production_plan(plan["id"], TEST_USERS["planner_headers"])
        )
        assert plan_after["shortfall_units"] == 100, (
            f"hop 1: plan shortfall must accrue batch qty 100, got {plan_after['shortfall_units']}"
        )

        stop_after = validate_success(
            api.get_route_stop(stop["id"], TEST_USERS["planner_headers"])
        )
        assert stop_after["shortfall_flag"] is True, (
            f"hop 2: PENDING stop referencing batch must be flagged, got {stop_after['shortfall_flag']}"
        )

        order_after = validate_success(
            api.get_store_order(order["id"], TEST_USERS["planner_headers"])
        )
        assert order_after["status"] == "SHORTED", (
            f"hop 3: order behind flagged stop must move LOCKED->SHORTED, got {order_after['status']}"
        )
