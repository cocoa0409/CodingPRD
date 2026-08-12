"""RBAC enforcement: role-based denials and unauthenticated access. Also the
subscription plan-change OCC stale-version rule and the body-FK
ERR_REFERENCE_NOT_FOUND rule.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    TEST_USERS,
    make_customer_headers,
    make_technician_headers,
    create_subscription_payload,
    create_customer,
    create_yard,
    create_access_profile,
    create_verified_access_profile,
    create_subscription_plan,
    create_technician,
    create_service_route,
    create_invoice,
    setup_active_subscription,
    setup_finalized_invoice,
    NON_EXISTENT_UUID,
)

OPS = TEST_USERS["ops_headers"]
BILLING = TEST_USERS["billing_headers"]


# =========================================================================
# Corner / rbac / technician_cannot_finalize_invoice
# Corner / rbac / customer_cannot_publish_route
# Corner / rbac / unauthenticated_request
# Corner / rbac / billing_admin_cannot_suspend_access_profile
# =========================================================================

class TestRbacDenials:
    def test_technician_cannot_finalize_invoice(self, api):
        """PRD §2.1: "If the role is recognized but is not permitted to invoke
        the endpoint in question, the request is rejected with
        `ERR_UNAUTHORIZED`." PRD §4 endpoint table authorizes only
        BillingAdmin for `POST /api/invoices/{id}/finalize`.

        Design: Corner/rbac/technician_cannot_finalize_invoice
        """
        customer = create_customer()
        api_client.set_current_utc("2026-06-01T00:00:00Z", OPS)
        invoice = create_invoice(customer["id"])
        technician = create_technician()
        resp = api_client.finalize_invoice(
            invoice["id"],
            {"expected_invoice_version": invoice["version"]},
            make_technician_headers(technician["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_customer_cannot_publish_route(self, api):
        """PRD §2.1: "If the role is recognized but is not permitted to invoke
        the endpoint in question, the request is rejected with
        `ERR_UNAUTHORIZED`." PRD §4 endpoint table authorizes only
        OperationsManager for `POST /api/service-routes/{id}/publish`.

        Design: Corner/rbac/customer_cannot_publish_route
        """
        customer = create_customer()
        technician = create_technician()
        route = create_service_route(
            route_code="RCP",
            service_date="2026-05-08T00:00:00Z",
            assigned_technician_id=technician["id"],
            max_visit_capacity=5,
        )
        resp = api_client.publish_service_route(
            route["id"], make_customer_headers(customer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "Every request to the API carries two HTTP headers:
        `X-User-ID` and `X-User-Role`. If either header is missing,
        malformed, or names a role the platform does not recognize, the
        request is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/unauthenticated_request
        """
        # Empty headers -> no X-User-ID / X-User-Role at all.
        resp = api_client.list_customers({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_billing_admin_cannot_suspend_access_profile(self, api):
        """PRD §2.1: "If the role is recognized but is not permitted to invoke
        the endpoint in question, the request is rejected with
        `ERR_UNAUTHORIZED`." PRD §4 endpoint table authorizes only
        OperationsManager for
        `POST /api/property-access-profiles/{id}/suspend`.

        Design: Corner/rbac/billing_admin_cannot_suspend_access_profile
        """
        customer = create_customer()
        yard = create_yard(customer["id"])
        profile = create_access_profile(yard["id"])
        resp = api_client.suspend_access_profile(
            profile["id"], {"reason": "test"}, BILLING
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# =========================================================================
# Corner / cross_cutting_complexity_layers / occ_subscription_plan_change_stale_version
# =========================================================================

class TestPlanChangeOcc:
    def test_plan_change_rejected_with_stale_expected_version(self, api):
        """PRD §2.7: "The first guarded endpoint is the plan-change action on
        a `Subscription`. The request must carry
        `expected_subscription_version` matching the subscription's current
        `version`. If another writer has advanced the subscription's version
        since the client last read it — for example by activating, pausing,
        or staging a different plan — the plan-change request is rejected
        with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/occ_subscription_plan_change_stale_version
        """
        api_client.set_current_utc("2026-05-01T00:00:00Z", OPS)
        customer = create_customer()
        yard = create_yard(customer["id"])
        create_verified_access_profile(yard["id"])
        plan_a = create_subscription_plan(plan_code="OCA", visit_frequency="WEEKLY")
        plan_b = create_subscription_plan(plan_code="OCB", visit_frequency="BIWEEKLY", base_monthly_fee_cents=8000)
        sub_resp = api_client.create_subscription(
            create_subscription_payload(customer["id"], yard["id"], plan_a["id"]),
            make_customer_headers(customer["id"]),
        )
        subscription = get_success_data(sub_resp)
        # Capture the pre-activation version, then activate (which bumps version).
        stale_version = subscription["version"]
        api_client.activate_subscription(
            subscription["id"], make_customer_headers(customer["id"])
        )
        # Now plan-change with the stale version.
        resp = api_client.plan_change_subscription(
            subscription["id"],
            {"new_plan_id": plan_b["id"], "expected_subscription_version": stale_version},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# =========================================================================
# Corner / errors / error_reference_not_found
# =========================================================================

class TestReferenceNotFound:
    def test_subscription_with_nonexistent_yard_rejected(self, api):
        """PRD §2.9 item 4: "Every foreign-key id in the request body
        (`customer_id`, `yard_id`, `plan_id`, every entry of `addon_ids`,
        `service_route_id`, `visit_id`, and analogous fields) resolves to an
        existing entity — otherwise `ERR_REFERENCE_NOT_FOUND`."

        Design: Corner/errors/error_reference_not_found
        """
        customer = create_customer()
        plan = create_subscription_plan()
        resp = api_client.create_subscription(
            {
                "customer_id": customer["id"],
                "yard_id": NON_EXISTENT_UUID,
                "plan_id": plan["id"],
            },
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)
