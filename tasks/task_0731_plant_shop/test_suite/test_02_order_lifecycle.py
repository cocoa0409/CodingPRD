"""Order lifecycle: parallel state dimensions, cross-entity gates, cancellation."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_error_is_one_of,
    get_success_data,
    set_clock, register_customer, create_driver, create_plant,
    intake_stock_unit, create_order, pay_order, dispatch_order, deliver,
    setup_delivered_orderline, get_orderline_id_for_order,
    TEST_USERS, make_customer_headers, make_delivery_driver_headers,
)


# -----------------------------------------------------------------------------
# Difficulty Rule 3: Non-linear state-machine shape (parallel dimensions)
# -----------------------------------------------------------------------------

class TestOrderParallelDimensions:

    def test_pay_flips_payment_dimension_only(self, api):
        """PRD §3.2: "The order-pay action moves PENDING+UNPAID to PENDING+PAID
        (payment dimension only) and bumps Order.version."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_payment_and_fulfillment_evolve_independently
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="eve@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Greg")
        plant = create_plant(
            name="Aloe", light_tag="DIRECT", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])

        resp = api.pay_order(order["id"], make_customer_headers(customer["id"]))
        paid = validate_success(resp)
        assert paid["payment_status"] == "PAID", "payment dimension flipped by /pay"
        assert paid["fulfillment_status"] == "PENDING", "fulfillment stays PENDING under /pay"

    def test_dispatch_flips_fulfillment_dimension_keeps_paid(self, api):
        """PRD §3.2: "The order-dispatch action requires Order.payment_status PAID
        and Order.fulfillment_status PENDING, verifies that every
        OrderLine.stock_unit_id resolves to a StockUnit currently in sale_status
        RESERVED, creates a DeliveryAssignment with status SCHEDULED, and moves
        the order from PENDING+PAID to DISPATCHED+PAID."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_payment_and_fulfillment_evolve_independently
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="eve2@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Greg2")
        plant = create_plant(
            name="Aloe2", light_tag="DIRECT", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        dispatch_order(order["id"], driver["id"], "2026-04-02T09:00:00Z", "2026-04-02T11:00:00Z")

        # Re-read via GET; the order should now be DISPATCHED+PAID.
        r = api.get_order(order["id"], make_customer_headers(customer["id"]))
        current = validate_success(r)
        assert current["payment_status"] == "PAID"
        assert current["fulfillment_status"] == "DISPATCHED"


# -----------------------------------------------------------------------------
# Difficulty Rule 7: Cross-entity state dependencies
# -----------------------------------------------------------------------------

class TestCrossEntityStateDependencies:

    def test_deliver_rejected_after_manager_cancels_dispatched_order(self, api):
        """PRD §3.2: "In the post-dispatch manager path, the associated
        DeliveryAssignment.status flips to FAILED and the reservation-release
        cascade runs identically."
        PRD §3.3: "The target DeliveryAssignment must be in SCHEDULED state, the
        acting DeliveryDriver.id must equal the assignment's driver_id
        (ownership check, or ERR_UNAUTHORIZED), and the parent order's
        payment_status must be PAID at the moment of finalization (a cross-entity
        gate)."

        Design: Difficulty/cross_entity_state_dependency/delivery_deliver_requires_order_paid
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="rita@example.com", delivery_zone="ZONE_A")
        driver = create_driver(name="Sam")
        plant = create_plant(
            name="Fern", light_tag="MEDIUM", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        delivery = dispatch_order(
            order["id"], driver["id"], "2026-04-02T09:00:00Z", "2026-04-02T11:00:00Z"
        )
        # Fetch fresh version for OCC-guarded cancel.
        current_order = get_success_data(api.get_order(order["id"], TEST_USERS["manager_headers"]))
        # Manager cancels dispatched paid order.
        r = api.cancel_order(
            order["id"],
            {"expected_order_version": current_order["version"]},
            TEST_USERS["manager_headers"],
        )
        validate_success(r)

        # Now attempt deliver — delivery.status was flipped to FAILED, so /deliver rejects.
        r2 = api.deliver_delivery(delivery["id"], make_delivery_driver_headers(driver["id"]))
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE.value)

    def test_warranty_submit_rejected_when_order_not_delivered(self, api):
        """PRD §3.5: "A WarrantyClaim targets a specific delivered OrderLine."
        PRD §2.8: "State preconditions. The target resource must be in a valid
        FROM state for the requested transition per the state machines described
        in §3. A precondition failure yields ERR_INVALID_STATE, applicable to
        every mutating action endpoint."

        Design: Difficulty/cross_entity_state_dependency/warranty_submit_requires_order_delivered
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="toni@example.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Rubber", light_tag="MEDIUM", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3500, warranty_days=60,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        # Fulfillment still PENDING — never dispatched, never delivered.
        orderline_id = get_orderline_id_for_order(order["id"], customer["id"])
        r = api.submit_warranty_claim(
            {"orderline_id": orderline_id, "customer_id": customer["id"], "reason": "MORTALITY"},
            make_customer_headers(customer["id"]),
        )
        # PRD prose commits that the target must be a delivered orderline, but does
        # not uniquely commit to the exact error_id. Accept either ERR_INVALID_STATE
        # or ERR_WARRANTY_NOT_ELIGIBLE (both are plausible PRD-faithful outcomes).
        validate_error_is_one_of(
            r,
            [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_WARRANTY_NOT_ELIGIBLE.value],
        )


# -----------------------------------------------------------------------------
# Corner: state_machines
# -----------------------------------------------------------------------------

class TestOrderTerminalCancellationRejected:

    def test_cancel_from_delivered_returns_invalid_state(self, api):
        """PRD §3.2: "The order-cancel action requires Order.fulfillment_status
        PENDING for the pre-dispatch path or DISPATCHED with payment_status PAID
        for the post-dispatch manager path".

        Design: Corner/state_machines/order_cancel_from_delivered_returns_invalid_state
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c1@x.com", delivery_zone="ZONE_A")
        driver = create_driver(name="D1")
        plant = create_plant(
            name="P1", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        delivery = dispatch_order(
            order["id"], driver["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z"
        )
        deliver(delivery["id"], driver["id"])
        # Order is now DELIVERED+PAID (terminal). Cancel must reject.
        current = get_success_data(api.get_order(order["id"], make_customer_headers(customer["id"])))
        r = api.cancel_order(
            order["id"],
            {"expected_order_version": current["version"]},
            make_customer_headers(customer["id"]),
        )
        validate_error(r, ApiErrorId.ERR_INVALID_STATE.value)


class TestSubscriptionPauseFromPaused:

    def test_pause_paused_subscription_rejected(self, api):
        """PRD §3.6: "An attempt to pause a subscription that is not in ACTIVE is
        rejected with ERR_SUBSCRIPTION_INACTIVE (HTTP 409)."

        Design: Corner/state_machines/subscription_pause_from_paused_returns_invalid_state
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c2@x.com", delivery_zone="ZONE_A")
        r_sub = api.create_subscription(
            {
                "customer_id": customer["id"],
                "plan_tier": "STARTER",
                "care_tag_preference": "EASY",
                "light_tag_preference": "LOW",
            },
            make_customer_headers(customer["id"]),
        )
        sub = validate_success(r_sub, expected_status=201)
        r_p = api.pause_subscription(sub["id"], make_customer_headers(customer["id"]))
        validate_success(r_p)
        # Second pause on PAUSED subscription:
        r_p2 = api.pause_subscription(sub["id"], make_customer_headers(customer["id"]))
        validate_error(r_p2, ApiErrorId.ERR_SUBSCRIPTION_INACTIVE.value)


class TestWorkshopCompletionState:

    def test_complete_workshop_before_end_at_returns_invalid_state(self, api):
        """PRD §3.7: "A manager marks the workshop complete through the
        workshop-completion action once the logical clock has reached or passed
        Workshop.end_at."

        Design: Corner/state_machines/workshop_complete_before_end_at_returns_invalid_state
        """
        set_clock("2026-04-30T09:00:00Z")
        r = api.create_workshop(
            {
                "title": "Early", "topic": "REPOTTING", "room_id": "STUDIO_A",
                "start_at": "2026-05-01T10:00:00Z", "end_at": "2026-05-01T12:00:00Z",
                "capacity": 10,
            },
            TEST_USERS["manager_headers"],
        )
        w = validate_success(r, expected_status=201)
        r2 = api.complete_workshop(w["id"], TEST_USERS["manager_headers"])
        validate_error(r2, ApiErrorId.ERR_INVALID_STATE.value)

    def test_complete_workshop_cascades_registered_to_attended(self, api):
        """PRD §3.7: "Completion cascades every registration currently in
        REGISTERED to ATTENDED (registrations already in CANCELLED are
        unaffected) and bumps the workshop's version once for the whole cascade."

        Design: Corner/state_machines/workshop_complete_cascades_registrations_to_attended
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c3@x.com", delivery_zone="ZONE_A")
        w = get_success_data(api.create_workshop(
            {
                "title": "Cascade", "topic": "REPOTTING", "room_id": "STUDIO_A",
                "start_at": "2026-04-10T10:00:00Z", "end_at": "2026-04-10T12:00:00Z",
                "capacity": 10,
            },
            TEST_USERS["manager_headers"],
        ))
        reg = get_success_data(api.register_workshop(
            w["id"], {"customer_id": customer["id"]}, make_customer_headers(customer["id"])
        ))
        # Advance past end_at, then complete.
        set_clock("2026-04-10T13:00:00Z")
        validate_success(api.complete_workshop(w["id"], TEST_USERS["manager_headers"]))
        # Registration cascades to ATTENDED.
        r = api.get_workshop_registration(reg["id"], TEST_USERS["manager_headers"])
        cascaded = validate_success(r)
        assert cascaded["status"] == "ATTENDED"
