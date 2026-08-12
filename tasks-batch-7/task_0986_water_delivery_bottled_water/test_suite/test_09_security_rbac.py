"""Security: role exclusivity and customer-self ownership checks."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_customer, setup_two_customers, set_clock, create_route, plan_stop,
    create_draft_invoice, create_pricing_config_payload,
    make_customer_self_headers, get_customer,
    OPS_ADMIN, DISPATCHER, DRIVER, BILLING_ADMIN,
)


class TestRoleExclusivity:
    def test_unauthorized_role_pricing_config_create(self, api):
        """PRD §2.1: "A request whose declared role is not permitted to invoke
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/api/v1/pricing-configs` | Create a pricing
        configuration | OpsAdmin |".

        Design: Corner/errors/unauthorized_role_pricing_config_create
        """
        set_clock("2026-05-01T00:00:00Z")
        res = api.create_pricing_config(create_pricing_config_payload(), DRIVER)
        validate_error(res, "ERR_UNAUTHORIZED")

    def test_dispatcher_cannot_issue_invoice(self, api):
        """PRD §2.1: "A request whose declared role is not permitted to invoke
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/api/v1/invoices/{id}/issue` | Issue a DRAFT invoice
        (DRAFT to OPEN); fires the automatic tier upgrade | BillingAdmin |".

        Design: Corner/rbac/dispatcher_cannot_issue_invoice
        """
        world = setup_customer(account_type="HOME", business_name="DC",
                               billing_email="d@x.example", service_address="1 D")
        invoice = create_draft_invoice(world["customer"]["id"], "2026-05-01",
                                       "2026-06-01", "2026-06-15")
        res = api.issue_invoice(invoice["id"], DISPATCHER)
        validate_error(res, "ERR_UNAUTHORIZED")

    def test_billing_admin_cannot_publish_route(self, api):
        """PRD §2.1: "A request whose declared role is not permitted to invoke
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "| POST | `/api/v1/routes/{id}/publish` | Publish a DRAFT route
        | Dispatcher |".

        Design: Corner/rbac/billing_admin_cannot_publish_route
        """
        world = setup_customer(account_type="HOME", business_name="BA",
                               billing_email="b@x.example", service_address="1 B",
                               service_mode="AUTO", par_level_bottles=1)
        route = create_route(world["zone"]["id"], "2026-06-01")
        plan_stop(route["id"], world["customer"]["id"], sequence_index=1)

        res = api.publish_route(route["id"], BILLING_ADMIN)
        validate_error(res, "ERR_UNAUTHORIZED")


class TestCustomerSelfOwnership:
    def test_customer_self_can_only_view_own_record(self, api):
        """PRD §2.1: "When `X-User-Role` is `CustomerSelf`, `X-User-ID` is the
        `id` of the acting `Customer`; ownership checks on any resource that
        references a customer compare the resource's `customer_id` field to
        `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/customer_self_can_only_view_own_record
        """
        world = setup_two_customers()
        c1, c2 = world["customer_a"], world["customer_b"]

        own = validate_success(
            api.get_customer(c1["id"], make_customer_self_headers(c1["id"])), 200)
        assert own["id"] == c1["id"]

        res = api.get_customer(c2["id"], make_customer_self_headers(c1["id"]))
        validate_error(res, "ERR_FORBIDDEN")
