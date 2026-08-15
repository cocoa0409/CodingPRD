"""Response envelope shapes, authentication, authorization, and VesselAgent
ownership scoping."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    create_berth,
    create_port_call_payload,
    create_terminal,
    create_vessel,
    delay_port_call_payload,
    make_vessel_agent_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HARBORMASTER = TEST_USERS["harbormaster_headers"]
CUSTOMS = TEST_USERS["customs_headers"]
BILLING = TEST_USERS["billing_headers"]


class TestResponseEnvelope:
    def test_success_and_error_envelope_shapes(self, api):
        """PRD §2.2: "- The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "- The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "- The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/endpoints/response_envelope_success_and_error_shapes
        """
        terminal = create_terminal()

        ok_resp = api.get_terminal(terminal["id"], HARBORMASTER)
        ok = validate_success(ok_resp)
        assert ok_resp.json()["response_type"] == "object"
        assert ok["id"] == terminal["id"]

        err_resp = api.get_terminal(NON_EXISTENT_UUID, HARBORMASTER)
        err = validate_error(err_resp, ApiErrorId.ERR_NOT_FOUND)
        assert err_resp.json()["response_type"] == "error"
        assert isinstance(err["message"], str) and err["message"].strip()


class TestAuthenticationAuthorization:
    def test_missing_auth_headers_returns_401(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or names
        an undeclared role, or whose `X-User-ID` is missing, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.9: "1. Authentication: the `X-User-Role` header is present and
        names a declared role, and `X-User-ID` is present — otherwise
        `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/missing_auth_headers_returns_401
        """
        resp = api.list_terminals(headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_wrong_role_actions_forbidden(self, api):
        """PRD §2.1: "A request whose role is declared but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.9: "2. Authorization: the role is permitted on this endpoint —
        otherwise `ERR_FORBIDDEN` (403)."
        PRD §2.9: "3. Existence: path ids and body foreign-key references exist,
        validated left-to-right — otherwise `ERR_NOT_FOUND` (404)."

        Design: Corner/rbac/wrong_role_actions_forbidden
        """
        terminal = create_terminal()
        berth = create_berth(terminal["id"])
        vessel = create_vessel(terminal["id"])
        agent = make_vessel_agent_headers(vessel["id"])
        port_call = validate_success(
            api.create_port_call(
                create_port_call_payload(terminal["id"], vessel["id"]), agent),
            201)
        assignment = validate_success(
            api.create_berth_assignment(
                port_call["id"],
                {"berth_id": berth["id"],
                 "window_start": "2026-08-10T06:00:00Z",
                 "window_end": "2026-08-10T22:00:00Z",
                 "expected_port_call_version": port_call["version"]},
                HARBORMASTER),
            201)

        # VesselAgent may not confirm berth assignments.
        err1 = api.confirm_berth_assignment(assignment["id"], agent)
        validate_error(err1, ApiErrorId.ERR_FORBIDDEN)

        # BillingClerk may not record an arrival.
        err2 = api.arrive_port_call(port_call["id"],
                                    {"actual_eta": "2026-08-10T08:00:00Z"},
                                    BILLING)
        validate_error(err2, ApiErrorId.ERR_FORBIDDEN)

        # CustomsOfficer may never board passengers; the role check fires even
        # before the (here nonexistent) entry's existence check.
        err3 = api.board_manifest_entry(NON_EXISTENT_UUID, CUSTOMS)
        validate_error(err3, ApiErrorId.ERR_FORBIDDEN)


class TestVesselAgentScope:
    def test_vessel_agent_scope_enforced_on_write_read_and_list(self, api):
        """PRD §2.1: "A `VesselAgent` acting on a port call whose `vessel_id`
        does not equal its `X-User-ID` — directly, or via a referenced child
        record of such a call — is rejected with `ERR_VESSEL_SCOPE` (HTTP 403).
        List endpoints filter to the agent's own vessel's calls;
        single-resource reads and child collections attached to another vessel's
        call are likewise rejected with `ERR_VESSEL_SCOPE`."
        PRD §2.9: "4. Vessel scope: a `VesselAgent`'s `X-User-ID` must equal the
        `vessel_id` of the owning port call, directly or via the referenced
        child — otherwise `ERR_VESSEL_SCOPE` (403)."

        Design: Corner/rbac/vessel_agent_scope_enforced
        """
        terminal = create_terminal()
        vessel_a = create_vessel(terminal["id"], name="MV A")
        vessel_b = create_vessel(terminal["id"], name="MV B", loa_ft=900,
                                 draft_ft=28.0, pax_capacity=3000, crew_count=800)
        port_call = validate_success(
            api.create_port_call(
                create_port_call_payload(terminal["id"], vessel_a["id"],
                                         voyage_ref="VA"),
                make_vessel_agent_headers(vessel_a["id"])),
            201)

        agent_b = make_vessel_agent_headers(vessel_b["id"])

        err1 = api.delay_port_call(
            port_call["id"],
            delay_port_call_payload(revised_eta="2026-08-11T08:00:00Z",
                                    revised_etd="2026-08-11T20:00:00Z",
                                    reason="slow steaming"),
            agent_b)
        validate_error(err1, ApiErrorId.ERR_VESSEL_SCOPE)

        err2 = api.get_port_call(port_call["id"], agent_b)
        validate_error(err2, ApiErrorId.ERR_VESSEL_SCOPE)

        _, meta = validate_paginated(
            api.list_port_calls(agent_b, params={"terminal_id": terminal["id"]}))
        assert meta["total_count"] == 0, (
            "another vessel's calls are filtered out of the agent's list view"
        )
