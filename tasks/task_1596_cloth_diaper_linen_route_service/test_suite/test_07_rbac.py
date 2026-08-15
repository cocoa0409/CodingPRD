"""Role-based access control: role listing, entity-backed ownership, and the
authentication stage (PRD 2.1)."""
from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    create_customer,
    create_pause_payload,
    create_plan,
    create_plan_payload,
    create_subscription,
    create_zone,
    fund_pool,
    generate_invoice_payload,
    make_customer_headers,
    make_route_driver_headers,
    set_clock,
    setup_active_subscription,
    setup_route_in_progress,
    validate_error,
    validate_success,
)
from test_helpers import api_client as _client


class TestAuthentication:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD 2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the operational
        capacity in which they act. A request with either header missing or malformed
        is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_returns_401
        """
        create_zone()
        response = _client.list_subscriptions(NO_AUTH_HEADERS)
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestRoleListing:
    def test_customer_cannot_create_subscription_plan(self, api):
        """PRD 2.1: "Beyond those shared capabilities, only a `PlatformAdmin` may
        create subscription plans, service zones, customers, subscriptions, routes,
        inventory pools, and wash formulas; sequence routes and drive route lifecycle
        events; fire customer lifecycle events; approve inventory swaps; and set the
        logical clock."

        Design: Corner/rbac/customer_cannot_create_subscription_plan
        """
        zone = create_zone()
        customer = create_customer(zone["id"])
        response = _client.create_plan(
            create_plan_payload(
                tier_code="HACK",
                weekly_quota=1,
                weekly_fee_cents=1,
                overage_rate_cents=0,
                deposit_cents=0,
                weight_policy="COUNT_BASIS",
            ),
            make_customer_headers(customer["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN.value)

    def test_driver_cannot_generate_invoice(self, api):
        """PRD 2.1: "Each endpoint lists the roles permitted to call it; a caller
        whose role is not listed, or an entity-backed caller reaching outside their
        own resources, is rejected with `ERR_FORBIDDEN`."
        PRD 4: "Generate a `DRAFT` weekly invoice | BillingAdmin, PlatformAdmin"

        Design: Corner/rbac/driver_cannot_generate_invoice
        """
        ctx = setup_active_subscription()
        response = _client.generate_invoice(
            generate_invoice_payload(ctx["subscription"]["id"]),
            make_route_driver_headers("drv-1"),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN.value)


class TestCustomerOwnership:
    def test_customer_cannot_pause_other_customers_subscription(self, api):
        """PRD 2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the
        acting `Customer`; ownership checks on any resource chained to a customer — a
        subscription, its service pauses, its inventory swaps, its invoices, its
        starter kit, its lost-item cases — compare the resource's chain back to the
        owning `customer_id` against `X-User-ID`, and a mismatch is `ERR_FORBIDDEN`."

        Design: Corner/rbac/customer_cannot_pause_other_customers_subscription
        """
        set_clock()
        plan = create_plan(tier_code="STANDARD")
        zone = create_zone()
        fund_pool("MEDIUM", 500)
        cust_a = create_customer(zone["id"], full_name="Owner A")
        cust_b = create_customer(zone["id"], full_name="Owner B")
        create_subscription(cust_a, plan, zone)
        sub_b = create_subscription(cust_b, plan, zone)

        response = _client.create_pause(
            create_pause_payload(
                sub_b["id"], "2026-08-05", "2026-08-10", sub_b["version"]
            ),
            make_customer_headers(cust_a["id"]),
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN.value)


class TestDriverAllowed:
    def test_driver_can_complete_assigned_stop(self, api):
        """PRD 3.3: "At the curb, a `RouteDriver` or `PlatformAdmin` completes a
        stop, recording `clean_items_delivered` and `soiled_bags_collected`."

        Design: Corner/rbac/driver_can_complete_assigned_stop
        """
        ctx = setup_active_subscription()
        setup_route_in_progress(ctx)

        completed = validate_success(
            _client.complete_stop(
                ctx["stop"]["id"],
                {
                    "soiled_bags_collected": 1,
                    "clean_items_delivered": 80,
                    "expected_route_version": ctx["route_version"],
                },
                make_route_driver_headers("drv-1"),
            )
        )
        assert completed["status"] == "COMPLETED"
