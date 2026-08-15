"""Response envelope, authentication, role authorization, and ownership scoping."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_exhibitor,
    create_exhibitor_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_exhibitor_headers,
    make_juror_headers,
    make_ops_headers,
    register_exhibitor,
    validate_error,
    validate_success,
)


class TestSuccessEnvelope:
    def test_success_envelope_shape(self, api, anonymous_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/endpoints/success_envelope_shape
        """
        resp = api.create_exhibitor(
            create_exhibitor_payload(legal_name="Dealer One LLC", category="DEALER"),
            anonymous_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert is_valid_uuid(body["data"]["id"])

    def test_error_envelope_shape(self, api, director_headers):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_space_unit(NON_EXISTENT_UUID, director_headers)
        error = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(error["message"], str) and error["message"].strip()
        body = resp.json()
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}


class TestAuthentication:
    def test_request_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside
        this list, is rejected with `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/request_missing_auth_headers_unauthenticated
        """
        resp = api.get_convention(NON_EXISTENT_UUID, headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_get_unknown_application_returns_not_found(self, api, director_headers):
        """PRD §2.8: "3. Existence — every identifier in the path, validated left
        to right, and every foreign-key field in the body must resolve to an
        existing resource; otherwise `ERR_NOT_FOUND`."

        Design: Corner/entities/get_unknown_application_returns_not_found
        """
        resp = api.get_application(NON_EXISTENT_UUID, director_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRoleAuthorization:
    def test_decide_forbidden_for_jury_member(self, api):
        """PRD §2.1: "A request whose authenticated role is not on the target
        operation's role list is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: "| POST | `/applications/{applicationId}/decide` | Jury decision:
        accept, waitlist, or reject | ShowDirector |"

        Design: Corner/rbac/decide_forbidden_for_jury_member
        """
        # Role authorization (priority 2) precedes existence (priority 3), so a
        # well-formed but nonexistent application id still yields 403.
        resp = api.decide_application(
            NON_EXISTENT_UUID, {"decision": "ACCEPTED"}, make_juror_headers("juror-1")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_space_unit_create_forbidden_for_exhibitor(self, api):
        """PRD §2.1: "A request whose authenticated role is not on the target
        operation's role list is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: "| POST | `/space-units` | Create one booth or table inventory
        unit | ShowDirector |"

        Design: Corner/rbac/space_unit_create_forbidden_for_exhibitor
        """
        resp = api.create_space_unit(
            {
                "convention_id": NON_EXISTENT_UUID,
                "space_code": "A-1",
                "block": "A",
                "unit_number": 1,
                "hall": "MAIN",
                "kind": "BOOTH_10X10",
                "base_price_cents": 100000,
            },
            make_exhibitor_headers(NON_EXISTENT_UUID),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_verify_permit_forbidden_for_operations_staff(self, api):
        """PRD §2.1: "A request whose authenticated role is not on the target
        operation's role list is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: "| POST | `/applications/{applicationId}/verify-permit` | Verify
        a submitted permit | ShowDirector |"

        Design: Corner/rbac/verify_permit_forbidden_for_operations_staff
        """
        resp = api.verify_permit(NON_EXISTENT_UUID, make_ops_headers("ops-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_anonymous_cannot_create_application(self, api, anonymous_headers):
        """PRD §2.1: "When `X-User-Role` is `Anonymous`, the caller is
        unregistered; the only operation open to this role is exhibitor
        self-registration."

        Design: Corner/rbac/anonymous_cannot_create_application
        """
        resp = api.create_application(
            {
                "convention_id": NON_EXISTENT_UUID,
                "category": "DEALER",
                "channel": "OPEN",
                "requested_space_kinds": ["BOOTH_10X10"],
                "requested_space_count": 1,
                "estimated_daily_sales_cents": 100,
            },
            anonymous_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


class TestExhibitorOwnership:
    def test_exhibitor_reads_own_record(self, api):
        """PRD §3.2: "The returned `id` becomes that exhibitor's `X-User-ID` for
        every later call, and an exhibitor may read only its own record."

        Design: Corner/rbac/exhibitor_reads_own_record
        """
        exhibitor = register_exhibitor(legal_name="Dealer One LLC", category="DEALER")
        resp = api.get_exhibitor(
            exhibitor["id"], make_exhibitor_headers(exhibitor["id"])
        )
        data = validate_success(resp)
        assert_exhibitor(data)
        assert data["legal_name"] == "Dealer One LLC"

    def test_exhibitor_reading_another_exhibitor_forbidden(self, api):
        """PRD §2.1: "List endpoints enforce this scoping themselves — an
        exhibitor listing applications is coerced to its own `exhibitor_id`
        filter, neighbor-request listings show only requests where the exhibitor
        is requester or target, staff, freight, and sales listings return only
        the exhibitor's own records, and reading an exhibitor record other than
        one's own is rejected with `ERR_FORBIDDEN_OWNERSHIP`."

        Design: Corner/rbac/exhibitor_reading_another_exhibitor_forbidden
        """
        ex_a = register_exhibitor(legal_name="Dealer A LLC", category="DEALER")
        ex_b = register_exhibitor(legal_name="Dealer B LLC", category="DEALER")
        resp = api.get_exhibitor(ex_a["id"], make_exhibitor_headers(ex_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
