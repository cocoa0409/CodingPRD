"""Response envelope shape, authentication, authorization, and existence."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_inspection_payload,
    create_mold_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
)


class TestResponseEnvelope:
    def test_success_envelope_shape(self, api, tooling_engineer_headers, shop_manager_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources." and "The `api_request_id` is a server-generated
        unique identifier for the request that starts with `req_`."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        mold = validate_success(
            api.create_mold(create_mold_payload(mold_code="MOLD-EN1"), tooling_engineer_headers),
            201,
        )
        res = api.get_mold(mold["id"], shop_manager_headers)
        body = res.json()
        assert res.status_code == 200
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["id"] == mold["id"]

    def test_error_envelope_shape(self, api, tooling_engineer_headers, shop_manager_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        validate_success(
            api.create_mold(create_mold_payload(mold_code="MOLD-EN1"), tooling_engineer_headers),
            201,
        )
        res = api.get_mold(NON_EXISTENT_UUID, shop_manager_headers)
        body = res.json()
        assert res.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose `X-User-Role`
        value is not one of these six declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.11: "Authentication comes first (missing or invalid headers,
        `ERR_UNAUTHENTICATED`), then authorization (role not permitted, `ERR_FORBIDDEN`)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        res = api.get_work_order(NON_EXISTENT_UUID, headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_undeclared_role_unauthenticated(self, api):
        """PRD §2.1: "A request whose headers are missing, or whose `X-User-Role`
        value is not one of these six declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        res = api.get_work_order(
            NON_EXISTENT_UUID, headers={"X-User-ID": "op-x", "X-User-Role": "SuperUser"}
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestExistence:
    def test_get_workorder_not_found_returns_404(self, api, shop_manager_headers):
        """PRD §2.11: "Existence follows: every identifier in the path and every
        foreign-key identifier in the request body is resolved left-to-right, and
        the first miss yields `ERR_NOT_FOUND`."

        Design: Corner/entities/get_workorder_not_found_returns_404
        """
        res = api.get_work_order(NON_EXISTENT_UUID, shop_manager_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestAuthorization:
    def test_laminator_cannot_create_inspection_forbidden(self, api, shop_manager_headers):
        """PRD §2.1: "A request whose role is valid but not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /inspections is authorized for QualityInspector only.
        PRD §2.11: authorization precedes existence, so the unknown work order id
        never earns its 404 here.

        Design: Corner/rbac/laminator_cannot_create_inspection_forbidden
        """
        res = api.create_inspection(
            create_inspection_payload(NON_EXISTENT_UUID),
            TEST_USERS["laminator_headers"],
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    def test_ehs_officer_cannot_create_mold(self, api, ehs_officer_headers):
        """PRD §2.1: "A request whose role is valid but not listed among the roles
        authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: POST /molds is authorized for ToolingEngineer only.

        Design: Corner/rbac/ehs_officer_cannot_create_mold
        """
        res = api.create_mold(create_mold_payload(mold_code="MOLD-RB1"), ehs_officer_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
