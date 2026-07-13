"""Order lifecycle: placement gating, payment, parallel axes, production/shipping, cancel cascade."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_approved_project, setup_laid_out_project, setup_paid_order,
    setup_order_with_done_job, setup_order_with_label, setup_order_delivered,
    place_order, get_production_job, advance_job_to_done,
    make_customer_headers,
)


class TestPlacementRequiresApprovedProject:
    """POST /orders is gated on the project's own state being APPROVED."""

    def test_draft_project_rejects_order(self, api):
        """PRD 3.5: "An order may be placed only when its project's state is APPROVED; otherwise
        placement is refused with ERR_PROJECT_NOT_APPROVED."

        Design: Difficulty/cross_entity_state_dependency/order_requires_project_approved
        """
        # A brand-new project is DRAFT; give the customer an address to reference.
        from test_helpers import create_customer, create_template, create_project, create_address
        cust = create_customer()
        h = make_customer_headers(cust["id"])
        tmpl = create_template()
        proj = create_project(cust, tmpl, headers=h)
        addr = create_address(cust["id"], headers=h)
        res = api.create_order({"project_id": proj["id"], "quantity": 5, "finish": "MATTE",
                                "ship_method": "STANDARD", "ship_address_id": addr["id"],
                                "payment_method": "CARD"}, h)
        validate_error(res, "ERR_PROJECT_NOT_APPROVED", 409)

    def test_laid_out_project_rejects_order(self, api):
        """PRD 3.5: "An order may be placed only when its project's state is APPROVED; otherwise
        placement is refused with ERR_PROJECT_NOT_APPROVED."

        Design: Difficulty/cross_entity_state_dependency/order_requires_project_approved
        """
        ctx = setup_laid_out_project()  # project is LAID_OUT (not APPROVED)
        from test_helpers import create_address
        addr = create_address(ctx["cust"]["id"], headers=ctx["headers"])
        res = api.create_order({"project_id": ctx["proj"]["id"], "quantity": 5, "finish": "MATTE",
                                "ship_method": "STANDARD", "ship_address_id": addr["id"],
                                "payment_method": "CARD"}, ctx["headers"])
        validate_error(res, "ERR_PROJECT_NOT_APPROVED", 409)


class TestImmediatePayment:
    """Paying advances both axes atomically and the response reflects the new state."""

    def test_pay_response_shows_paid_and_in_production(self, api):
        """PRD 3.5: "On success the order's payment_status becomes PAID and its paid_cents is set
        equal to total_cents"
        PRD 3.5: "Payment also kicks the fulfillment axis: fulfillment_status moves from NEW to
        IN_PRODUCTION, and a production job is spawned in QUEUED state"

        Design: Corner/consistency_model/corner_immediate_pay_response_reflects_state
        """
        ctx = setup_approved_project()
        order = place_order(ctx)
        paid = validate_success(api.pay_order(order["id"], ctx["headers"]), 200)
        assert paid["payment_status"] == "PAID"
        assert paid["fulfillment_status"] == "IN_PRODUCTION"

    def test_paying_already_paid_order_rejected(self, api):
        """PRD 3.5: "Payment is admissible only when payment_status is UNPAID (else
        ERR_ORDER_NOT_PAYABLE)"

        Design: Corner/state_machines/corner_pay_already_paid_rejected
        """
        ctx = setup_paid_order()
        res = api.pay_order(ctx["order"]["id"], ctx["headers"])
        validate_error(res, "ERR_ORDER_NOT_PAYABLE", 409)


class TestParallelAxes:
    """payment_status and fulfillment_status advance on independent axes."""

    def test_fulfillment_reaches_delivered(self, api):
        """PRD 3.6: "when the shipment enters IN_TRANSIT the order's fulfillment_status becomes
        SHIPPED, and when the shipment reaches DELIVERED the order's fulfillment_status becomes
        DELIVERED."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_axes
        """
        from test_helpers import TEST_USERS
        ctx = setup_order_delivered()  # shipment IN_TRANSIT, order SHIPPED
        validate_success(api.advance_shipment(ctx["shipment"]["id"], TEST_USERS["production_operator_headers"]), 200)
        order = validate_success(api.get_order(ctx["order"]["id"], ctx["headers"]), 200)
        assert order["fulfillment_status"] == "DELIVERED", f"got {order['fulfillment_status']}"

    def test_payment_axis_stays_paid_across_fulfillment_advances(self, api):
        """PRD 3.5: "On success the order's payment_status becomes PAID and its paid_cents is set
        equal to total_cents"
        PRD 3.6: "when the shipment reaches DELIVERED the order's fulfillment_status becomes DELIVERED."

        Design: Difficulty/non_linear_state_machine/order_parallel_payment_fulfillment_axes
        """
        from test_helpers import TEST_USERS
        ctx = setup_order_delivered()  # shipment IN_TRANSIT
        api.advance_shipment(ctx["shipment"]["id"], TEST_USERS["production_operator_headers"])  # -> DELIVERED
        order = validate_success(api.get_order(ctx["order"]["id"], ctx["headers"]), 200)
        assert order["fulfillment_status"] == "DELIVERED"
        assert order["payment_status"] == "PAID", f"payment axis unchanged, got {order['payment_status']}"


class TestShipmentRequiresDoneJob:
    """A shipment can be created only after the order's production job reaches DONE."""

    def test_queued_job_blocks_shipment(self, api):
        """PRD 3.6: "Only once the order's production job has reached DONE may a shipment be created
        for that order; attempting it earlier is refused with ERR_PRODUCTION_NOT_COMPLETE."

        Design: Difficulty/cross_entity_state_dependency/shipment_requires_job_done
        """
        from test_helpers import TEST_USERS
        ctx = setup_paid_order()  # job is QUEUED
        res = api.create_shipment(ctx["order"]["id"],
                                  {"address_id": ctx["addr"]["id"], "carrier": "UPS", "method": "STANDARD"},
                                  TEST_USERS["production_operator_headers"])
        validate_error(res, "ERR_PRODUCTION_NOT_COMPLETE", 409)

    def test_printing_job_blocks_shipment(self, api):
        """PRD 3.6: "Only once the order's production job has reached DONE may a shipment be created
        for that order; attempting it earlier is refused with ERR_PRODUCTION_NOT_COMPLETE."

        Design: Difficulty/cross_entity_state_dependency/shipment_requires_job_done
        """
        from test_helpers import TEST_USERS
        op = TEST_USERS["production_operator_headers"]
        ctx = setup_paid_order()
        job = get_production_job(ctx["order"])
        api.advance_job(job["id"], op)  # QUEUED -> PRINTING (still not DONE)
        res = api.create_shipment(ctx["order"]["id"],
                                  {"address_id": ctx["addr"]["id"], "carrier": "UPS", "method": "STANDARD"}, op)
        validate_error(res, "ERR_PRODUCTION_NOT_COMPLETE", 409)

    def test_advancing_done_job_rejected(self, api):
        """PRD 3.6: "Advancing a job that is not in an advanceable state — including one already at
        DONE — is refused with ERR_PRODUCTION_NOT_ADVANCEABLE"

        Design: Corner/state_machines/corner_advance_done_job_rejected
        """
        from test_helpers import TEST_USERS
        ctx = setup_order_with_done_job()
        res = api.advance_job(ctx["job"]["id"], TEST_USERS["production_operator_headers"])
        validate_error(res, "ERR_PRODUCTION_NOT_ADVANCEABLE", 409)


class TestCancelCascade:
    """Cancelling cascades Order -> ProductionJob -> Shipment (depth 3)."""

    def test_cancel_sets_order_and_job_cancelled(self, api):
        """PRD 3.7: "The order's fulfillment_status becomes CANCELLED. Any production job of the
        order that is not already CANCELLED — including one that has reached DONE — is moved to
        CANCELLED"

        Design: Difficulty/transitive_cascade/cancel_cascade_order_job_shipment_void
        """
        ctx = setup_order_with_label()  # job DONE, shipment LABEL_CREATED, order IN_PRODUCTION
        order = validate_success(api.cancel_order(ctx["order"]["id"], {"refund_destination": "CARD"}, ctx["headers"]), 200)
        assert order["fulfillment_status"] == "CANCELLED"
        job = get_production_job(ctx["order"])
        assert job["state"] == "CANCELLED", f"job cascaded to CANCELLED, got {job['state']}"

    def test_cancel_voids_live_shipment(self, api):
        """PRD 3.7: "voids any shipment of the order still in LABEL_CREATED or IN_TRANSIT by setting
        that shipment's state to VOID."

        Design: Difficulty/transitive_cascade/cancel_cascade_order_job_shipment_void
        """
        from test_helpers import TEST_USERS
        ctx = setup_order_with_label()
        api.cancel_order(ctx["order"]["id"], {"refund_destination": "CARD"}, ctx["headers"])
        shipment = validate_success(api.get_shipment(ctx["shipment"]["id"], TEST_USERS["production_operator_headers"]), 200)
        assert shipment["state"] == "VOID", f"shipment voided by job cancel, got {shipment['state']}"

    def test_cancel_shipped_order_rejected(self, api):
        """PRD 3.7: "cancelling an order that is already SHIPPED, DELIVERED, or CANCELLED is refused
        with ERR_ORDER_NOT_CANCELLABLE."

        Design: Corner/state_machines/corner_cancel_shipped_order_rejected
        """
        ctx = setup_order_delivered()  # shipment IN_TRANSIT -> order fulfillment SHIPPED
        res = api.cancel_order(ctx["order"]["id"], {"refund_destination": "CARD"}, ctx["headers"])
        validate_error(res, "ERR_ORDER_NOT_CANCELLABLE", 409)


class TestReorderAndListing:

    def test_reorder_creates_linked_unpaid_order(self, api):
        """PRD 3.7: "The new order's reorder_of_id is set to the source order's id, and the source
        order's quantity, finish, and project are copied forward"

        Design: Corner/endpoints/corner_reorder_creates_linked_unpaid_order
        """
        ctx = setup_paid_order(order_overrides={"quantity": 5})
        src = ctx["order"]
        new = validate_success(api.reorder(src["id"], {}, ctx["headers"]), 201)
        assert new["reorder_of_id"] == src["id"]
        assert new["payment_status"] == "UNPAID"
        assert new["quantity"] == 5, f"quantity copied forward, got {new['quantity']}"

    def test_list_orders_filtered_by_customer(self, api):
        """PRD 2.3: "The meta block of a list response carries the pagination fields limit, offset,
        total_count, and has_more, where total_count is the number of records matching the query
        before pagination and has_more is true when records remain beyond the returned page."

        Design: Corner/endpoints/corner_list_orders_filter_by_customer
        """
        ctx = setup_approved_project()
        order = place_order(ctx)
        res = api.list_orders(ctx["headers"], params={"customer_id": ctx["cust"]["id"]})
        data, meta = validate_paginated(res)
        assert any(o["id"] == order["id"] for o in data), "customer's order must appear in the list"
        assert "total_count" in meta and "has_more" in meta
