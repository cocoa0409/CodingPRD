"""Owner onboarding, response envelope, and authentication basics (PRD §2.1, §2.2, §3.1)."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    ApiErrorId,
    TEST_USERS,
    create_owner_payload,
    create_bicycle_payload,
    register_owner,
    assert_owner,
    NON_EXISTENT_UUID,
)


class TestOwnerRegistration:
    def test_owner_registration_required_fields_created_201(self, api):
        """PRD §4: "Operations that create a new resource — registering an owner,
        onboarding a partner organization, registering a bicycle, initiating a
        transfer, filing a theft report, recording an intake, filing a claim,
        scheduling an auction, placing a bid, creating an event, booking a seat,
        or raising a duplicate flag — return `201 Created`."
        PRD §3.1: "An owner's record also exposes `bikes_registered_count`, a
        computed count of the bicycles whose `current_owner_id` is this owner
        and whose `integrity_status` is not `MERGED`."

        Design: Corner/entities/owner_registration_required_fields_created_201
        """
        resp = api.register_owner(
            create_owner_payload(email="new@x.com", full_name="New Owner"),
            TEST_USERS["anonymous_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_owner(data)
        assert data["version"] == 1, f"fresh owner version must be 1, got {data['version']}"
        assert data["bikes_registered_count"] == 0, (
            f"fresh owner must have 0 registered bikes, got {data['bikes_registered_count']}"
        )

    def test_owner_registration_missing_email_returns_invalid_request(self, api):
        """PRD §3.1: "An `Anonymous` visitor joins the platform by self-registering
        an owner account with an `email`, a `password`, and a `full_name`."
        PRD §2.6: "required fields are present, types are correct, enum values are
        in range" and "failures yield `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/owner_registration_missing_email_returns_invalid_request
        """
        resp = api.register_owner(
            {"password": "pw", "full_name": "No Email"},
            TEST_USERS["anonymous_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_owner_not_found_returns_404(self, api, registrar_headers):
        """PRD §2.6: "each identifier in the URL path must resolve to an existing
        row, checked sequentially from the leftmost segment; the first unresolvable
        segment produces its entity-specific 404: `ERR_OWNER_NOT_FOUND`"

        Design: Corner/entities/owner_not_found_returns_404
        """
        resp = api.get_owner(NON_EXISTENT_UUID, registrar_headers)
        validate_error(resp, ApiErrorId.ERR_OWNER_NOT_FOUND, expected_status=404)


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success(self, api):
        """PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
        timestamp with three fractional digits."

        Design: Corner/endpoints/response_envelope_shape_on_success
        """
        resp = api.register_owner(
            create_owner_payload(email="env@x.com", full_name="Env"),
            TEST_USERS["anonymous_headers"],
        )
        assert resp.status_code == 201, f"expected 201, got {resp.status_code}"
        body = resp.json()
        assert "meta" in body and "data" in body, "envelope must carry meta and data"
        request_id = body["meta"].get("api_request_id", "")
        assert isinstance(request_id, str) and request_id.startswith("req_"), (
            f"meta.api_request_id must start with 'req_', got {request_id!r}"
        )
        assert is_iso8601_timestamp(body["meta"].get("api_request_timestamp", "")), (
            "meta.api_request_timestamp must be an ISO 8601 timestamp"
        )
        assert body["response_type"] == "object", (
            f"single-resource creation must carry response_type 'object', "
            f"got {body['response_type']!r}"
        )
        assert is_valid_uuid(body["data"].get("id", ""))


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request with missing or malformed headers, or whose
        `X-User-Role` is not one of these five declared values, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_bicycle(
            create_bicycle_payload(serial_number="NOAUTH1", declared_value_cents=10000),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)

    def test_anonymous_cannot_register_bicycle(self, api, anonymous_headers):
        """PRD §2.1: "A request whose role is well-formed but not permitted for the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "an `Anonymous` caller may do exactly one thing, self-register an
        owner account."

        Design: Corner/rbac/anonymous_cannot_register_bicycle
        """
        resp = api.create_bicycle(
            create_bicycle_payload(serial_number="RBC300", declared_value_cents=10000),
            anonymous_headers,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
