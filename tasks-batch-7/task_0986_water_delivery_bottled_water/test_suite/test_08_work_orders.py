"""Work orders: scheduling requires an ACTIVE customer."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_suspended_customer, create_work_order_payload, create_route,
    pay_invoice, get_customer, get_work_order, get_route, get_stop,
    OPS_ADMIN, DISPATCHER, BILLING_ADMIN,
)


class TestScheduleRequiresActiveCustomer:
    def _suspended_with_pending_order(self, api):
        """Suspended customer (unpaid invoice) plus a fresh PENDING delivery
        order and a route standing on its requested date."""
        scenario = setup_suspended_customer(delivery_date="2026-05-05")
        customer_id = scenario["customer"]["id"]
        order = get_success_data(api_client.create_work_order(
            create_work_order_payload(customer_id, "DELIVERY", "2026-06-20", 2),
            DISPATCHER))
        route = create_route(scenario["zone"]["id"], "2026-06-20")
        return scenario, order, route

    def test_schedule_rejected_when_customer_suspended(self, api):
        """PRD §3.6: "Scheduling is the dispatcher's commit. A `PENDING` order
        may be scheduled only while the customer is `ACTIVE`."
        PRD §2.6: "Whether the target resource is in a state that permits the
        requested transition — violations return `ERR_INVALID_STATE`; an
        operation attempted on a resource already sitting in a terminal state is
        instead rejected with `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/cross_entity_state_dependency/workorder_schedule_requires_customer_active
        """
        scenario, order, route = self._suspended_with_pending_order(api)
        assert scenario["customer"]["account_status"] == "SUSPENDED"

        res = api.schedule_work_order(order["id"], DISPATCHER)
        validate_error(res, "ERR_INVALID_STATE")
        after = get_work_order(order["id"])
        assert after["order_status"] == "PENDING", \
            f"rejected scheduling must leave the order PENDING, got {after['order_status']}"
        assert after["linked_stop_id"] is None

    def test_schedule_succeeds_after_reinstatement(self, api):
        """PRD §3.6: "Scheduling is the dispatcher's commit. A `PENDING` order
        may be scheduled only while the customer is `ACTIVE`. For `DELIVERY` and
        `EXCHANGE_ONLY` orders, scheduling requires a route already existing on
        the `requested_date` in the zone matching the customer's
        `delivery_zone_id`, with that route still in `DRAFT` or `PUBLISHED`;
        scheduling then creates a stop on that route whose `planned_bottles`
        equals the order's `quantity_bottles`, sets the order's
        `linked_stop_id`, and adds those bottles to the route's
        `committed_bottles` — subject to the same truck-capacity ceiling, so an
        over-capacity schedule is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`."
        PRD §3.2: "Reinstatement returns a `SUSPENDED` account to `ACTIVE`, but
        only once `outstanding_balance_cents` has returned to zero — the debt
        must actually be cleared, not merely promised."

        Clearing the debt and reinstating flips the same scheduling call to a
        success, pinning the dependency on the customer's state.

        Design: Difficulty/cross_entity_state_dependency/workorder_schedule_requires_customer_active
        """
        scenario, order, route = self._suspended_with_pending_order(api)
        customer_id = scenario["customer"]["id"]

        pay_invoice(scenario["invoice"]["id"], scenario["invoice"]["total_due_cents"])
        assert get_customer(customer_id)["outstanding_balance_cents"] == 0
        reinstated = validate_success(api.reinstate_customer(customer_id, OPS_ADMIN), 200)
        assert reinstated["account_status"] == "ACTIVE"

        scheduled = validate_success(api.schedule_work_order(order["id"], DISPATCHER), 200)
        assert scheduled["order_status"] == "SCHEDULED"
        assert scheduled["linked_stop_id"] is not None, \
            "scheduling a delivery order must create and link a stop"
        stop = get_stop(scheduled["linked_stop_id"])
        assert stop["planned_bottles"] == 2, \
            f"the stop's planned bottles equal the order quantity, got {stop['planned_bottles']}"
        route_after = get_route(route["id"])
        assert route_after["committed_bottles"] == 2, (
            f"the stop's bottles join the route commitment, "
            f"got {route_after['committed_bottles']}"
        )
