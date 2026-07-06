"""Validation, RBAC ownership, and reverse-reachability corner tests."""
import pytest

from test_helpers import (
    ApiErrorId, validate_success, validate_error, get_success_data,
    set_clock, register_customer, create_driver, create_plant,
    intake_stock_unit, create_order, pay_order, dispatch_order,
    TEST_USERS, make_customer_headers, make_delivery_driver_headers,
)


# -----------------------------------------------------------------------------
# Corner: entities — shape/enum/existence
# -----------------------------------------------------------------------------

class TestCustomerRegistrationShapeAndExistence:

    def test_customer_register_missing_email_returns_invalid_request(self, api):
        """PRD §3.2: "The registration payload supplies email (a unique lowercase
        address matching the pattern ^[^@]+@[^@]+\\.[^@]+$)".
        PRD §2.8: "All required input fields must be present, enum values must
        fall within their declared constraints, and types must match. Unknown
        extra fields are ignored. Shape violations yield ERR_INVALID_REQUEST."

        Design: Corner/entities/customer_register_missing_required_field_returns_invalid_request
        """
        r = api.register_customer(
            {"full_name": "NoEmail", "delivery_zone": "ZONE_A", "address_line": "1 X"},
            TEST_USERS["anonymous_headers"],
        )
        validate_error(r, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_get_non_existent_customer_returns_not_found(self, api):
        """PRD §2.8: "Every path parameter and every foreign key in the payload
        must reference an existing entity. Path parameters resolve left-to-right
        in the URL: for a nested path such as /plants/{id}/stock-units, the
        Plant referenced by {id} is resolved before any child lookup. A missing
        target yields ERR_NOT_FOUND."

        Design: Corner/entities/customer_get_non_existent_returns_not_found
        """
        r = api.get_customer("00000000-0000-4000-8000-000000000000", TEST_USERS["manager_headers"])
        validate_error(r, ApiErrorId.ERR_NOT_FOUND.value)

    def test_plant_create_invalid_light_tag_enum_returns_invalid_request(self, api):
        """PRD §3.1: "a light requirement light_tag chosen from LOW, MEDIUM,
        BRIGHT_INDIRECT, or DIRECT".
        PRD §2.8: "All required input fields must be present, enum values must
        fall within their declared constraints, and types must match. Unknown
        extra fields are ignored. Shape violations yield ERR_INVALID_REQUEST."

        Design: Corner/entities/plant_create_invalid_enum_light_tag_returns_invalid_request
        """
        r = api.create_plant(
            {
                "name": "P", "light_tag": "NEON", "care_tag": "EASY",
                "weight_class": "LIGHT", "unit_price_cents": 1000, "warranty_days": 30,
            },
            TEST_USERS["manager_headers"],
        )
        validate_error(r, ApiErrorId.ERR_INVALID_REQUEST.value)


# -----------------------------------------------------------------------------
# Corner: validations — violation → error
# -----------------------------------------------------------------------------

class TestBusinessFiscalAndReferentialValidations:

    def test_applied_redemption_exceeds_balance_returns_insufficient_loyalty(self, api):
        """PRD §3.2: "If the customer supplies a positive
        applied_redemption_cents, two ceilings apply. The requested value may
        not exceed the customer's current points_balance at the one-cent-per-
        point conversion, and it may not exceed the sum of the order's line
        subtotals; either overflow is rejected with ERR_INSUFFICIENT_LOYALTY
        (HTTP 402)."

        Design: Corner/validations/order_applied_redemption_exceeds_balance_returns_insufficient_loyalty
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c6@x.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Rp", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        r = api.create_order(
            {
                "customer_id": customer["id"], "delivery_zone": "ZONE_A",
                "applied_redemption_cents": 100,
                "lines": [{"plant_id": plant["id"], "qty": 1}],
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(r, ApiErrorId.ERR_INSUFFICIENT_LOYALTY.value)

    def test_order_delivery_zone_mismatch_returns_out_of_zone(self, api):
        """PRD §3.2: "the delivery_zone snapshot at checkout (which must equal
        the customer's own delivery_zone — mismatch is ERR_DELIVERY_OUT_OF_ZONE,
        HTTP 422)".

        Design: Corner/validations/order_delivery_zone_mismatch_returns_out_of_zone
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c7@x.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Zn", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        r = api.create_order(
            {
                "customer_id": customer["id"], "delivery_zone": "ZONE_C",
                "lines": [{"plant_id": plant["id"], "qty": 1}],
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(r, ApiErrorId.ERR_DELIVERY_OUT_OF_ZONE.value)

    def test_order_no_available_stock_returns_stock_unavailable(self, api):
        """PRD §3.2: "If the plant's available_count is less than the line's qty,
        or no FOR_SALE, HEALTHY stock unit exists at all, checkout is rejected
        with ERR_STOCK_UNAVAILABLE (HTTP 409)."

        Design: Corner/validations/order_no_available_stock_returns_stock_unavailable
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c8@x.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Empty", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        # No stock unit created!
        r = api.create_order(
            {
                "customer_id": customer["id"], "delivery_zone": "ZONE_A",
                "lines": [{"plant_id": plant["id"], "qty": 1}],
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(r, ApiErrorId.ERR_STOCK_UNAVAILABLE.value)


# -----------------------------------------------------------------------------
# Corner: errors — order-cancel stale version
# -----------------------------------------------------------------------------

class TestOrderCancelOCC:

    def test_cancel_with_pre_pay_version_returns_stale_version(self, api):
        """PRD §2.7: "Order cancellation. The order-cancel action (driven by
        POST /orders/{id}/cancel) requires the client to send a non-optional
        expected_order_version matching the target Order's current version. If
        any prior write — payment, dispatch, delivery finalization, or a
        cascade from another operation — has advanced the order's version since
        the client's last read, the cancel is rejected with ERR_STALE_VERSION
        (HTTP 412)."

        Design: Corner/errors/err_stale_version_on_order_cancel
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c15@x.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="St", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        v_at_create = order["version"]
        # Pay bumps version.
        pay_order(order["id"], customer["id"])
        r = api.cancel_order(
            order["id"],
            {"expected_order_version": v_at_create},
            make_customer_headers(customer["id"]),
        )
        validate_error(r, ApiErrorId.ERR_STALE_VERSION.value)


# -----------------------------------------------------------------------------
# Corner: RBAC — role & ownership denials
# -----------------------------------------------------------------------------

class TestRbacRoleAndOwnership:

    def test_horticulturist_cannot_create_plant(self, api):
        """PRD §4: PRD table row "POST | /plants | Create a plant SKU. | Manager"
        together with PRD §2.1: "When the role and identity headers are valid but
        the role is not permitted for the requested operation, or when an
        entity-backed role attempts to act on a resource it does not own, the
        response is ERR_UNAUTHORIZED (HTTP 403)."

        Design: Corner/rbac/horticulturist_cannot_create_plant_returns_unauthorized
        """
        r = api.create_plant(
            {
                "name": "X", "light_tag": "LOW", "care_tag": "EASY",
                "weight_class": "LIGHT", "unit_price_cents": 3000, "warranty_days": 30,
            },
            TEST_USERS["horticulturist_headers"],
        )
        validate_error(r, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_customer_b_cannot_cancel_customer_a_order(self, api):
        """PRD §2.1: "This role is entity-backed by Customer: when X-User-Role is
        Customer, X-User-ID is the id of the acting Customer, and ownership
        checks on any resource that references a Customer compare the resource's
        foreign-key field (customer_id) to X-User-ID. This ownership check
        governs a customer's own orders, subscriptions, warranty claims,
        workshop registrations, care reminders, and special orders."
        PRD §2.8: "For entity-backed roles, X-User-ID must equal the acting
        entity's id on ownership-scoped endpoints — a Customer acting on an
        order, subscription, warranty claim, workshop registration, care
        reminder, or special order must match customer_id, and a DeliveryDriver
        acting on a delivery assignment must match driver_id. A mismatch is
        also ERR_UNAUTHORIZED."

        Design: Corner/rbac/customer_cannot_cancel_another_customers_order_returns_unauthorized
        """
        set_clock("2026-04-01T00:00:00Z")
        cust_a = register_customer(email="c17@x.com", delivery_zone="ZONE_A")
        cust_b = register_customer(email="c18@x.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Own", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(cust_a["id"], [(plant["id"], 1)])
        r = api.cancel_order(
            order["id"],
            {"expected_order_version": order["version"]},
            make_customer_headers(cust_b["id"]),
        )
        validate_error(r, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_driver_b_cannot_deliver_driver_a_assignment(self, api):
        """PRD §2.1: "DeliveryDriver — the assigned driver. This role is
        entity-backed by DeliveryDriver: when X-User-Role is DeliveryDriver,
        X-User-ID is the id of the acting DeliveryDriver, and ownership checks
        on a delivery assignment compare that assignment's driver_id to
        X-User-ID. A driver may finalize only the deliveries assigned to them."

        Design: Corner/rbac/driver_cannot_deliver_someone_elses_assignment_returns_unauthorized
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c19@x.com", delivery_zone="ZONE_A")
        driver_a = create_driver(name="DriverA")
        driver_b = create_driver(name="DriverB")
        plant = create_plant(
            name="D", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        order = create_order(customer["id"], [(plant["id"], 1)])
        pay_order(order["id"], customer["id"])
        delivery = dispatch_order(
            order["id"], driver_a["id"], "2026-04-02T09:00:00Z", "2026-04-02T10:00:00Z"
        )
        r = api.deliver_delivery(delivery["id"], make_delivery_driver_headers(driver_b["id"]))
        validate_error(r, ApiErrorId.ERR_UNAUTHORIZED.value)


# -----------------------------------------------------------------------------
# Corner: endpoints — filtered list & reverse-reachability
# -----------------------------------------------------------------------------

class TestFilteredListEndpoints:

    def test_get_orders_filtered_by_customer_returns_only_owner_orders(self, api):
        """PRD §2.10: "Filtered-list endpoints that live off the top of the URL
        tree (order-lines, deliveries, subscriptions, workshop registrations,
        warranty claims, special orders, care reminders) expose the parent
        foreign keys as query parameters, so that a client may enumerate a
        customer's warranty claims, a driver's deliveries, or an order's lines
        without descending into a nested path."

        Design: Corner/endpoints/get_orders_filtered_by_customer_id_returns_only_owner_orders
        """
        set_clock("2026-04-01T00:00:00Z")
        cust_a = register_customer(email="c12@x.com", delivery_zone="ZONE_A")
        cust_b = register_customer(email="c13@x.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Xy", light_tag="LOW", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=3000, warranty_days=30,
        )
        intake_stock_unit(plant["id"], acquisition_date="2026-03-20T00:00:00Z")
        intake_stock_unit(plant["id"], acquisition_date="2026-03-21T00:00:00Z")
        order_a = create_order(cust_a["id"], [(plant["id"], 1)])
        create_order(cust_b["id"], [(plant["id"], 1)])
        r = api.list_orders(
            make_customer_headers(cust_a["id"]), params={"customer_id": cust_a["id"]}
        )
        from test_helpers import validate_paginated
        data, meta = validate_paginated(r)
        assert len(data) == 1, f"expected 1 order in filter, got {len(data)}"
        assert data[0]["id"] == order_a["id"]

    def test_care_reminders_filtered_by_customer_returns_array(self, api):
        """PRD §2.10: "Filtered-list endpoints that live off the top of the URL
        tree (order-lines, deliveries, subscriptions, workshop registrations,
        warranty claims, special orders, care reminders) expose the parent
        foreign keys as query parameters".
        PRD §2.2: "The response_type is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/care_reminders_filtered_by_customer_id_reverse_reachability
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c14@x.com", delivery_zone="ZONE_A")
        r = api.list_care_reminders(
            make_customer_headers(customer["id"]), params={"customer_id": customer["id"]}
        )
        # No care reminders exist yet; response should still be an array-shaped success.
        from test_helpers import validate_paginated
        data, meta = validate_paginated(r)
        assert isinstance(data, list)


# -----------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers — scheduler advances next_fulfillment 30d
# -----------------------------------------------------------------------------

class TestSchedulerAdvancesNextFulfillment:

    def test_scheduler_advances_next_fulfillment_by_30_days_on_hit(self, api):
        """PRD §3.6: "On a hit, the scheduler creates an Order with a single
        OrderLine for the selected unit, with payment_status PAID (auto-charged
        against the plan's stub), transitions a MISSING_STOCK subscription back
        to ACTIVE, advances Subscription.next_fulfillment_at by 30 days, and
        bumps the subscription's version."

        Design: Corner/cross_cutting_complexity_layers/scheduler_fulfill_advances_next_fulfillment_by_30_days
        """
        set_clock("2026-04-01T00:00:00Z")
        customer = register_customer(email="c20@x.com", delivery_zone="ZONE_A")
        plant = create_plant(
            name="Match", light_tag="MEDIUM", care_tag="EASY",
            weight_class="LIGHT", unit_price_cents=2500, warranty_days=30,
        )
        intake_stock_unit(plant["id"])
        sub = get_success_data(api.create_subscription(
            {
                "customer_id": customer["id"], "plan_tier": "STARTER",
                "care_tag_preference": "EASY", "light_tag_preference": "MEDIUM",
            },
            make_customer_headers(customer["id"]),
        ))
        # next_fulfillment_at at create = 2026-05-01T00:00:00Z
        set_clock("2026-05-05T00:00:00Z")
        validate_success(api.scheduler_fulfill_subscriptions(TEST_USERS["manager_headers"]))
        after = get_success_data(api.get_subscription(sub["id"], make_customer_headers(customer["id"])))
        # Advanced by 30 days from prior value = 2026-05-31T00:00:00Z
        assert after["next_fulfillment_at"].startswith("2026-05-31T00:00:00")
