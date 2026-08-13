"""Authentication context, role authorization, and resource not-found errors."""
import pytest

from test_helpers import (
    ANY_H,
    INSPECTOR,
    INSTALLER,
    NON_EXISTENT_UUID,
    TECH,
    ApiErrorId,
    create_min_model,
    create_reman_order_payload,
    draft_calibration,
    drive_order_to_calibration,
    get_claim,
    get_order,
    setup_submitted_claim,
    api_client,
    validate_error,
    validate_success,
)


class TestAuthenticationContext:

    def test_missing_auth_headers_rejected(self):
        """PRD §2.1: "A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_rejected
        """
        model = create_min_model()
        resp = api_client.create_reman_order(
            create_reman_order_payload(model["id"], "BUYER-1"), headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleAuthorization:

    def test_inspector_cannot_create_reman_order(self):
        """PRD §2.1: "When the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /api/reman-orders is authorized for RemanPlanner only.

        Design: Corner/rbac/inspector_cannot_create_reman_order
        """
        model = create_min_model()
        resp = api_client.create_reman_order(
            create_reman_order_payload(model["id"], "BUYER-1"), INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_installer_cannot_approve_claim(self):
        """PRD §2.1: "When the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /api/warranty-claims/{id}/approve is authorized for WarrantyAdjuster only.

        Design: Corner/rbac/installer_cannot_approve_claim
        """
        _m, _o, claim = setup_submitted_claim()
        resp = api_client.approve_claim(claim["id"], INSTALLER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = get_claim(claim["id"])
        assert after["claim_status"] == "SUBMITTED", \
            "a forbidden approval must not adjudicate the claim"

    def test_technician_cannot_verify_calibration(self):
        """PRD §2.1: "When the named role is not permitted to invoke the endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4: POST /api/reman-orders/{id}/verify-calibration is authorized for Calibrator only.

        Design: Corner/rbac/technician_cannot_verify_calibration
        """
        model = create_min_model()
        order = drive_order_to_calibration(model["id"])
        draft_calibration(order["id"])
        resp = api_client.verify_calibration(order["id"], TECH)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = get_order(order["id"])
        assert after["cal_status"] == "DRAFT"


class TestResourceNotFound:

    def test_order_get_not_found(self):
        """PRD §2.8: "identifiers in the path are validated first, then foreign-key identifiers in the body, working left to right; the first unknown identifier yields its specific 404: ... `ERR_ORDER_NOT_FOUND` ...".

        Design: Corner/entities/order_get_not_found_returns_404
        """
        resp = api_client.get_reman_order(NON_EXISTENT_UUID, ANY_H)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_invoice_get_not_found(self):
        """PRD §2.8: "the first unknown identifier yields its specific 404: `ERR_MODEL_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_INTERCHANGE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_DYNO_RUN_NOT_FOUND`, `ERR_CORE_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_CLAIM_NOT_FOUND`."

        Design: Corner/errors/invoice_get_not_found_returns_404
        """
        resp = api_client.get_core_deposit_invoice(NON_EXISTENT_UUID, ANY_H)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_FOUND)
