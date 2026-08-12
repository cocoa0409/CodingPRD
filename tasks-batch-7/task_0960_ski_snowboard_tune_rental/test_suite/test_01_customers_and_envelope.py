"""Customer registration, creation defaults, and response-envelope contracts."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_customer,
    create_customer_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_customer,
    validate_error,
    validate_success,
)

FD = TEST_USERS["front_desk_headers"]


class TestCustomerCreation:
    def test_created_customer_starts_in_good_standing(self, api):
        """PRD Customer Profiles: "Every customer starts in `GOOD_STANDING` with a
        `late_return_count` of zero."
        PRD Common Resource Properties: "`version` (integer): starts at 1 at creation
        and increments by exactly 1 on every mutation."

        Design: Corner/entities/customer_create_applies_defaults
        """
        resp = api.create_customer(create_customer_payload(), FD)
        data = validate_success(resp, expected_status=201)
        assert_customer(data)
        assert data["standing"] == "GOOD_STANDING"
        assert data["late_return_count"] == 0
        assert data["version"] == 1

    def test_created_customer_has_iso8601_timestamps(self, api):
        """PRD Common Resource Properties: "`created_at` (string): an ISO 8601 UTC
        timestamp with three fractional digits recording when the resource was created."

        Design: Corner/entities/customer_create_applies_defaults
        """
        customer = make_customer()
        for field in ("created_at", "updated_at"):
            value = customer[field]
            assert is_iso8601_timestamp(value), f"{field} not ISO 8601 UTC: {value!r}"
            assert "." in value, f"{field} must carry fractional digits: {value!r}"
            fractional = value.split(".", 1)[1].rstrip("Z")
            assert len(fractional) == 3, (
                f"{field} must have three fractional digits: {value!r}"
            )

    def test_create_customer_missing_email_rejected(self, api):
        """PRD Customer Profiles: "A `FrontDesk` or `Manager` operator registers each
        customer with their `full_name`, a unique `email`, and the physical profile that
        drives binding fitment"; the only 400-class input error is ERR_INVALID_REQUEST.

        Design: Corner/entities/customer_missing_required_email_returns_invalid_request
        """
        payload = create_customer_payload()
        del payload["email"]
        resp = api.create_customer(payload, FD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_get_customer_not_found(self, api):
        """PRD Request Validation Precedence: "every identifier in the path and every
        foreign-key identifier in the body is resolved for existence, strictly left to
        right along the path first, producing `ERR_NOT_FOUND` for the first identifier
        that does not correspond to an existing resource."

        Design: Corner/entities/customer_get_not_found_returns_404
        """
        resp = api.get_customer(NON_EXISTENT_UUID, FD)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestResponseEnvelope:
    def test_success_envelope_shape_on_create(self, api):
        """PRD Standard Success Response Format: "The `api_request_id` is a
        server-generated unique identifier for the request that starts with `req_`" and
        "The `response_type` is either "object" for a single resource or "array" for a
        list of resources."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        resp = api.create_customer(create_customer_payload(), FD)
        body = resp.json()
        assert resp.status_code == 201
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert is_valid_uuid(body["data"]["id"])

    def test_error_envelope_shape_on_not_found(self, api):
        """PRD Standard Error Response Format: "The `error_id` is a unique,
        machine-readable string that identifies the specific error. The `message`
        provides a human-readable explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape_on_not_found
        """
        resp = api.get_customer(NON_EXISTENT_UUID, FD)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
