"""API envelope shape, authentication context, and role-based access control."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_billing_cycle_payload,
    create_district_payload,
    create_meter_reading_payload,
    create_payment_payload,
    get_success_data,
    setup_billed_invoice,
    setup_member_with_installed_tap,
    submit_reading,
    open_cycle,
    bill_cycle_with_readings,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, CLERK, FIELD, TREASURER


class TestEnvelopeShape:
    def test_success_envelope_carries_meta_and_object_response_type(self, api):
        """PRD section 2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        resp = api.create_district(create_district_payload(district_name="OB"), ADMIN)
        data = validate_success(resp, expected_status=201)
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert data["district_name"] == "OB"

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD section 2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error." and "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        resp = api.get_district(NON_EXISTENT_UUID, ADMIN)
        error = validate_error(resp, ApiErrorId.ERR_DISTRICT_NOT_FOUND, expected_status=404)
        body = resp.json()
        assert body["response_type"] == "error"
        assert error["message"].strip()


class TestAuthenticationContext:
    def test_request_without_user_headers_rejected(self, api):
        """PRD section 2.1: "If either header is missing, or the role value is
        not one of the declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/rbac_missing_headers_unauthenticated
        """
        resp = api.list_districts(headers={})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, expected_status=400
        )


class TestRoleBasedAccess:
    def test_billing_clerk_cannot_collect_payment(self, api):
        """PRD section 2.1: "If the role is valid but not permitted for the
        endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." Payment collection is a Treasurer endpoint per the PRD
        endpoint table (POST /districts/{id}/payments — Treasurer).

        Design: Corner/rbac/rbac_billing_clerk_cannot_collect_payment
        """
        ctx = setup_billed_invoice(usage_gallons=100)
        district = ctx["district"]
        invoice = ctx["invoice"]
        resp = api.create_payment(
            district["id"],
            create_payment_payload(ctx["member"]["id"], invoice["id"], 3500),
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
        # No payment row was created
        payments = get_success_data(api.list_payments(district["id"], TREASURER))
        assert payments == [], f"Expected no payments after 403, got {payments}"

    def test_treasurer_cannot_bill_cycle(self, api):
        """PRD section 2.1: "If the role is valid but not permitted for the
        endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)." Billing a cycle is a BillingClerk endpoint per the PRD
        endpoint table (POST .../billing-cycles/{cycleId}/bill — BillingClerk).

        Design: Corner/rbac/rbac_treasurer_cannot_bill_cycle
        """
        ctx = setup_member_with_installed_tap()
        district = ctx["district"]
        cycle = get_success_data(
            api.create_billing_cycle(district["id"], create_billing_cycle_payload(), CLERK),
            expected_status=201,
        )
        get_success_data(
            api.create_meter_reading(
                district["id"],
                create_meter_reading_payload(ctx["tap"]["id"], cycle["id"], 100),
                FIELD,
            ),
            expected_status=201,
        )
        get_success_data(api.mark_readings_complete(district["id"], cycle["id"], CLERK))
        resp = api.bill_cycle(district["id"], cycle["id"], TREASURER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
        after = get_success_data(api.get_billing_cycle(district["id"], cycle["id"], CLERK))
        assert after["status"] == "READINGS_COMPLETE", (
            f"Cycle must remain READINGS_COMPLETE after a denied bill, got {after['status']}"
        )


class TestNotFound:
    def test_get_district_with_unknown_id_returns_404(self, api):
        """PRD section 2.7: "any id that does not exist, or that exists under a
        different district, yields the corresponding not-found error
        (`ERR_DISTRICT_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_TAP_NOT_FOUND`,
        `ERR_CYCLE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`,
        `ERR_PETITION_NOT_FOUND`, `ERR_RESOLUTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_SAMPLE_NOT_FOUND`, `ERR_AREA_NOT_FOUND`, or `ERR_PAYMENT_NOT_FOUND`),
        all HTTP 404."

        Design: Corner/entities/district_not_found_returns_404
        """
        resp = api.get_district(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DISTRICT_NOT_FOUND, expected_status=404)
