"""Customer lifecycle: closure gates, terminal lockdown, and suspension cascade."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_customer, create_work_order_payload, create_route,
    pay_invoice, get_customer, get_stop, get_route, get_work_order,
    OPS_ADMIN, DISPATCHER,
)


class TestCustomerLifecycle:
    def test_customer_terminal_close_lockdown(self, api):
        """PRD §3.2: "Either way the account lands in `CLOSED` with its
        `updated_at` refreshed and `version` incremented, and `CLOSED` is terminal."
        PRD §2.6: "Whether the target resource is in a state that permits the
        requested transition — violations return `ERR_INVALID_STATE`; an operation
        attempted on a resource already sitting in a terminal state is instead
        rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/customer_terminal_close_lockdown
        """
        world = setup_customer(account_type="HOME", business_name="TermCo",
                               billing_email="t@x.example", service_address="1 T")
        customer = world["customer"]
        closed = validate_success(api.close_customer(customer["id"], OPS_ADMIN), 200)
        assert closed["account_status"] == "CLOSED"

        res = api.suspend_customer(customer["id"], OPS_ADMIN)
        validate_error(res, "ERR_ALREADY_TERMINAL")

    def test_customer_close_blocked_by_bottles(self, api):
        """PRD §3.2: "From `ACTIVE`, closure requires `outstanding_balance_cents`
        at zero (otherwise `ERR_OUTSTANDING_BALANCE`), `bottles_on_site` at zero
        (otherwise `ERR_BOTTLES_OUTSTANDING`), and no cooler rental standing in
        `INSTALLED`, `SUSPENDED`, or `RETURN_REQUESTED`; a clean closure cancels
        every add-on on the account and voids every `DRAFT` or `OPEN` invoice."

        Setup delivers one bottle and collects no empties (a partial delivery),
        leaving the customer holding bottle custody even after the invoice is
        paid in full, so closure is gated on bottle custody alone.

        Design: Corner/validations/customer_close_blocked_by_bottles
        """
        from test_helpers import deliver_via_work_order, create_and_issue_invoice
        world = setup_customer(account_type="HOME", business_name="BalCo",
                               billing_email="b@x.example", service_address="1 B",
                               service_mode="WILL_CALL", par_level_bottles=0,
                               pricing_tier="STANDARD")
        zone, customer = world["zone"], world["customer"]
        deliver_via_work_order(customer["id"], zone["id"], "2026-05-05", 1,
                               actual_bottles_delivered=1, actual_empties_collected=0)
        invoice = create_and_issue_invoice(customer["id"], "2026-05-01", "2026-06-01",
                                           "2026-06-15")
        pay_invoice(invoice["id"], invoice["total_due_cents"])
        settled = get_customer(customer["id"])
        assert settled["outstanding_balance_cents"] == 0, \
            "setup: balance must be zero so only bottle custody gates closure"
        assert settled["bottles_on_site"] > 0, \
            "setup: customer must still hold bottle custody"

        res = api.close_customer(customer["id"], OPS_ADMIN)
        validate_error(res, "ERR_BOTTLES_OUTSTANDING")

    def test_suspend_cancels_pending_work_orders(self, api):
        """PRD §3.2: "Suspension is a hard stop with cascading consequences:
        every work order still `PENDING` for the customer is cancelled, every
        `PLANNED` stop for the customer on a future route is cancelled (releasing
        its bottles from the route's commitment), and the customer's `updated_at`
        refreshes while `version` increments."

        Design: Difficulty/transitive_cascade/customer_suspend_cascade_depth3
        """
        scenario = setup_suspended_customer_ready()
        customer_id = scenario["customer"]["id"]

        res = api.suspend_customer(customer_id, OPS_ADMIN)
        suspended = validate_success(res, 200)
        assert suspended["account_status"] == "SUSPENDED"

        pending = get_work_order(scenario["pending_order"]["id"])
        assert pending["order_status"] == "CANCELLED", (
            f"PENDING work order must be cancelled by suspension, "
            f"got {pending['order_status']}"
        )

    def test_suspend_cancels_planned_stops_and_releases_commitment(self, api):
        """PRD §3.2: "Suspension is a hard stop with cascading consequences:
        every work order still `PENDING` for the customer is cancelled, every
        `PLANNED` stop for the customer on a future route is cancelled (releasing
        its bottles from the route's commitment), and the customer's `updated_at`
        refreshes while `version` increments."

        Design: Difficulty/transitive_cascade/customer_suspend_cascade_depth3
        """
        scenario = setup_suspended_customer_ready()
        route_id = scenario["future_route"]["id"]
        stop_id = scenario["future_stop"]["id"]
        before = get_route(route_id)
        assert before["committed_bottles"] == scenario["future_stop"]["planned_bottles"]

        validate_success(api.suspend_customer(scenario["customer"]["id"], OPS_ADMIN), 200)

        stop_after = get_stop(stop_id)
        assert stop_after["stop_status"] == "CANCELLED", (
            f"PLANNED stop on a future route must be cancelled by suspension, "
            f"got {stop_after['stop_status']}"
        )
        route_after = get_route(route_id)
        assert route_after["committed_bottles"] == 0, (
            f"cancellation must release the stop's planned bottles, "
            f"got committed_bottles={route_after['committed_bottles']}"
        )


def setup_suspended_customer_ready() -> dict:
    """Customer with an unpaid issued invoice, plus one PENDING work order and
    one SCHEDULED work order whose PLANNED stop sits on a future route."""
    from test_helpers import deliver_via_work_order, create_and_issue_invoice
    world = setup_customer(account_type="OFFICE", business_name="Cascade1",
                           billing_email="c@c1.example", service_address="1 A St",
                           service_mode="WILL_CALL", par_level_bottles=0,
                           pricing_tier="STANDARD")
    zone, customer = world["zone"], world["customer"]

    # Generate an outstanding balance so suspension is permitted.
    delivery = deliver_via_work_order(customer["id"], zone["id"], "2026-05-10", 3)
    invoice = create_and_issue_invoice(customer["id"], "2026-05-01", "2026-06-01",
                                       "2026-06-15")

    # One order left PENDING, one order scheduled onto a future route.
    pending = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer["id"], "DELIVERY", "2026-06-20", 2),
        DISPATCHER))
    scheduled = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer["id"], "DELIVERY", "2026-06-25", 4),
        DISPATCHER))
    future_route = create_route(zone["id"], "2026-06-25")
    scheduled = get_success_data(api_client.schedule_work_order(scheduled["id"], DISPATCHER))
    future_stop = get_stop(scheduled["linked_stop_id"])

    return {
        "zone": zone,
        "customer": get_customer(customer["id"]),
        "invoice": invoice,
        "route": delivery["route"],
        "pending_order": pending,
        "scheduled_order": scheduled,
        "future_route": future_route,
        "future_stop": future_stop,
    }
