"""Authentication, authorization, and the error envelope."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    is_iso8601_timestamp,
    make_reviewer_headers,
    validate_error,
)

P = TEST_USERS["principal_headers"]


class TestAuthentication:

    def test_missing_auth_header_rejected(self):
        """PRD §2.1: "Every request must carry `X-User-ID`, identifying the
        acting user, and `X-User-Role`, declaring the capacity in which that
        user acts. A request missing either header, or carrying an empty value
        for either, is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        payload = {"name": "NA", "client_name": "C", "fee_cap_cents": 1000,
                   "labor_rate_cents_per_hour": 100}
        # No X-User-ID at all.
        resp = api_client.create_engagement(
            payload, {"X-User-Role": "Principal",
                      "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT)
        # No X-User-Role at all.
        resp = api_client.create_engagement(
            payload, {"X-User-ID": "user-1",
                      "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT)
        # Empty X-User-ID value.
        resp = api_client.create_engagement(
            payload, {"X-User-ID": "", "X-User-Role": "Principal",
                      "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT)


class TestAuthorization:

    def test_forbidden_role_on_exclusive_endpoint(self):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: the create-engagement endpoint row lists `Principal` as its
        only authorized role.

        Design: Corner/validations/forbidden_role_on_exclusive_endpoint
        """
        resp = api_client.create_engagement(
            {"name": "FR", "client_name": "C", "fee_cap_cents": 1000,
             "labor_rate_cents_per_hour": 100},
            make_reviewer_headers("rev-user-1"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestErrorEnvelope:

    def test_error_envelope_shape(self):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api_client.get_engagement(NON_EXISTENT_UUID, P)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip()
