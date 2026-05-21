"""Envelope shape, auth headers, RBAC, ownership, and 404 cascade."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_flight,
    create_member,
    create_segment_for_member,
    make_member_headers,
    validate_error,
    validate_success,
)


class TestSuccessEnvelope:

    def test_create_member_success_envelope(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" — meta, response_type, data.
        """
        member = create_member()
        # Envelope structure already validated by get_success_data; here
        # we re-issue the call and check the raw body.
        resp = api.create_member(
            {"email": f"x-{member['email']}", "display_name": "X",
             "home_region": "DOMESTIC"},
            TEST_USERS["program_admin_headers"],
        )
        body = resp.json()
        assert "meta" in body
        assert "response_type" in body
        assert body["response_type"] == "object"
        assert "data" in body
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id is a server-generated unique "
            "identifier for the request that starts with req_."
        )


class TestAuthHeaders:

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header ... is rejected
        with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
        """
        # Build headers without X-User-ID.
        bad = {"X-User-Role": "ProgramAdmin",
               "Content-Type": "application/json"}
        resp = api._request("GET", "/flights", headers=bad)
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header ... is rejected
        with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
        """
        bad = {"X-User-ID": "some-id", "Content-Type": "application/json"}
        resp = api._request("GET", "/flights", headers=bad)
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )


class TestRoleForbidden:

    def test_member_cannot_create_flight(self, api):
        """PRD §4 table: POST /flights is ProgramAdmin only. PRD §2.1:
        "A request whose role lacks permission for the endpoint is
        rejected with ERR_FORBIDDEN."
        """
        member = create_member()
        resp = api.create_flight(
            {"flight_number": "AA1", "origin": "JFK", "destination": "LAX",
             "distance_miles": 1000, "route_region": "DOMESTIC",
             "departure_at": "2099-01-01T00:00:00.000Z",
             "base_fare_cents": 50_000},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_booking_agent_cannot_run_sweeps(self, api,
                                              booking_agent_headers):
        """PRD §4 table: POST /_sweep/* is ProgramAdmin only."""
        resp = api.sweep_expire_points(booking_agent_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestOwnership:

    def test_member_cannot_read_other_members_segment(self, api):
        """PRD §2.1: "A Member who acts on a resource owned by a
        different member is rejected with ERR_OWNERSHIP_MISMATCH."

        PRD §2.6: "a FlightSegment whose member_id does not equal the
        path's memberId yields ERR_SEGMENT_NOT_FOUND" — this is the
        nested-existence rule. For an own-resource action with a
        member's own member_id mismatching the resource owner via the
        path member id, the response is ERR_SEGMENT_NOT_FOUND because
        the path nesting evaluates first; but if the path matches owner
        A and the header X-User-ID identifies member B, the ownership
        rule applies and ERR_OWNERSHIP_MISMATCH is the answer.
        """
        flight = create_flight()
        owner_a = create_member()
        owner_b = create_member()
        seg = create_segment_for_member(owner_a["id"], flight["id"])
        # Member B cancels owner-A's segment using a path that names
        # owner A but headers that identify owner B.
        resp = api.cancel_segment(
            owner_a["id"], seg["id"], make_member_headers(owner_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)


class TestExistenceCascade:

    def test_missing_member_yields_member_not_found(self, api,
                                                     admin_headers):
        """PRD §2.6: "The request is rejected with the existence error
        corresponding to the first identifier in the path that does not
        correspond to an existing resource — ERR_MEMBER_NOT_FOUND before
        any segment lookup."
        """
        resp = api.list_segments(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND.value)

    def test_missing_segment_yields_segment_not_found(self, api):
        """PRD §2.6: "ERR_SEGMENT_NOT_FOUND before any upgrade-request
        lookup."""
        member = create_member()
        resp = api.create_upgrade_request(
            member["id"], NON_EXISTENT_UUID,
            {"target_cabin": "FIRST", "points_offered": 5_000},
            make_member_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_FOUND.value)

    def test_segment_owned_by_other_member_yields_segment_not_found(
        self, api,
    ):
        """PRD §2.6: "a FlightSegment whose member_id does not equal the
        path's memberId yields ERR_SEGMENT_NOT_FOUND."

        Here the path member exists, but the segment id belongs to
        someone else.
        """
        flight = create_flight()
        owner_a = create_member()
        owner_b = create_member()
        seg_b = create_segment_for_member(owner_b["id"], flight["id"])
        # Call addressed to owner_a's namespace; segment belongs to B.
        resp = api.cancel_segment(
            owner_a["id"], seg_b["id"], make_member_headers(owner_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_FOUND.value)
