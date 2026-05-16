"""Auth, RBAC, response envelope, pagination, and NotFound.

PRD §2.1 (auth/role), §2.2 (envelope), §2.3 (pagination), §2.6 (NotFound).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_program_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing headers
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Requests missing either header on any endpoint
        that requires authentication are rejected with ERR_AUTH_MISSING."

        Claim: a POST with neither header set -> ERR_AUTH_MISSING.
        """
        res = api.create_program(create_program_payload(), headers={})
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Requests missing either header on any endpoint
        that requires authentication are rejected with ERR_AUTH_MISSING."

        Claim: omitting X-User-ID but supplying X-User-Role ->
        ERR_AUTH_MISSING.
        """
        res = api.create_program(
            create_program_payload(),
            headers={"X-User-Role": "ComplianceOfficer"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Requests missing either header on any endpoint
        that requires authentication are rejected with ERR_AUTH_MISSING."

        Claim: omitting X-User-Role but supplying X-User-ID ->
        ERR_AUTH_MISSING.
        """
        res = api.create_program(
            create_program_payload(),
            headers={"X-User-ID": "officer-001"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_invalid_role_value_rejected(self, api):
        """PRD §2.1: "If X-User-Role is supplied but is not one of the
        five recognized role names listed below, the request is
        rejected with ERR_AUTH_INVALID_ROLE."

        Claim: X-User-Role="Hacker" -> ERR_AUTH_INVALID_ROLE.
        """
        res = api.list_programs(
            headers=build_user_headers("u-1", "Hacker"),
        )
        validate_error(res, "ERR_AUTH_INVALID_ROLE")


# ===========================================================================
# §2.1 RBAC — endpoint authorization
# ===========================================================================
class TestRBACForbidden:
    """PRD §2.1: "A request that passes the header and role-name
    checks but targets an endpoint not permitted for that role under
    the RBAC matrix in §4 is rejected with ERR_FORBIDDEN."
    """

    def test_coach_cannot_create_program(self, api):
        """PRD §4 endpoint table: POST /programs is restricted to
        ComplianceOfficer.
        PRD §2.1: "A request that passes the header and role-name
        checks but targets an endpoint not permitted for that role
        under the RBAC matrix in §4 is rejected with ERR_FORBIDDEN."

        Claim: Coach calling POST /programs -> ERR_FORBIDDEN.
        """
        res = api.create_program(
            create_program_payload(),
            headers=TEST_USERS["coach_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_athlete_cannot_create_scholarship_slot(self, api, officer_headers):
        """PRD §4 endpoint table: POST /scholarship-slots is restricted
        to Coach.
        PRD §2.1: "A request that passes the header and role-name
        checks but targets an endpoint not permitted for that role
        under the RBAC matrix in §4 is rejected with ERR_FORBIDDEN."

        Claim: Athlete calling POST /scholarship-slots -> ERR_FORBIDDEN.
        """
        from test_helpers import (
            create_athlete,
            create_scholarship_slot_payload,
            make_athlete_headers,
        )
        athlete = create_athlete()
        res = api.create_scholarship_slot(
            create_scholarship_slot_payload(
                program_id=NON_EXISTENT_UUID,
                athlete_id=athlete["id"],
            ),
            headers=make_athlete_headers(athlete["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_auditor_cannot_create_program(self, api):
        """PRD §4 endpoint table: POST /programs is restricted to
        ComplianceOfficer; Auditor is read-everywhere only.
        PRD §2.1: "A request that passes the header and role-name
        checks but targets an endpoint not permitted for that role
        under the RBAC matrix in §4 is rejected with ERR_FORBIDDEN."

        Claim: Auditor calling POST /programs -> ERR_FORBIDDEN.
        """
        res = api.create_program(
            create_program_payload(),
            headers=TEST_USERS["auditor_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.6 Path NotFound
# ===========================================================================
class TestPathNotFound:
    """PRD §2.6: "the first identifier in the URL that does not resolve
    to a stored resource produces a 404 with ERR_NOT_FOUND, and the
    server does not look further down the path."""

    def test_get_program_with_unknown_id_returns_not_found(
        self, api, officer_headers,
    ):
        """PRD §2.6: "the first identifier in the URL that does not
        resolve to a stored resource produces a 404 with ERR_NOT_FOUND."

        Claim: GET /programs/{unknown-uuid} -> ERR_NOT_FOUND.
        """
        res = api.get_program(NON_EXISTENT_UUID, officer_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_athlete_with_unknown_id_returns_not_found(
        self, api, officer_headers,
    ):
        """PRD §2.6: "the first identifier in the URL that does not
        resolve to a stored resource produces a 404 with ERR_NOT_FOUND."

        Claim: GET /athletes/{unknown-uuid} -> ERR_NOT_FOUND.
        """
        res = api.get_athlete(NON_EXISTENT_UUID, officer_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_state_transition_on_unknown_athlete_returns_not_found(
        self, api, officer_headers,
    ):
        """PRD §2.6: "the first identifier in the URL that does not
        resolve to a stored resource produces a 404 with ERR_NOT_FOUND."

        Claim: POST /athletes/{unknown}/state -> ERR_NOT_FOUND.
        """
        from test_helpers import transition_athlete_payload
        res = api.transition_athlete(
            NON_EXISTENT_UUID,
            transition_athlete_payload(to_status="ENROLLED"),
            officer_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.6 Body reference resolution
# ===========================================================================
class TestBodyReferenceResolution:
    """PRD §2.6: "references such as athlete_id, program_id,
    related_athlete_id, related_deal_id, and destination_program_id are
    resolved before any business validation runs; an unresolved body
    reference is reported as ERR_REFERENCE_NOT_FOUND."""

    def test_create_eligibility_record_with_unknown_athlete_id(
        self, api, officer_headers,
    ):
        """PRD §2.6: "an unresolved body reference is reported as
        ERR_REFERENCE_NOT_FOUND."

        Claim: POST /eligibility-records with athlete_id pointing at a
        non-existent athlete -> ERR_REFERENCE_NOT_FOUND.
        """
        from test_helpers import create_eligibility_record_payload
        res = api.create_eligibility_record(
            create_eligibility_record_payload(
                athlete_id=NON_EXISTENT_UUID,
            ),
            officer_headers,
        )
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")

    def test_create_nil_deal_with_unknown_athlete_id(
        self, api, officer_headers,
    ):
        """PRD §2.6: "an unresolved body reference is reported as
        ERR_REFERENCE_NOT_FOUND."

        Claim: POST /nil-deals with athlete_id pointing at a
        non-existent athlete -> ERR_REFERENCE_NOT_FOUND.
        """
        from test_helpers import create_nil_deal_payload
        res = api.create_nil_deal(
            create_nil_deal_payload(athlete_id=NON_EXISTENT_UUID),
            officer_headers,
        )
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: success responses carry meta + response_type + data."""

    def test_success_envelope_has_meta_and_data(self, api, officer_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format" with
        api_request_id starting with `req_` and an ISO 8601
        api_request_timestamp.

        Claim: a 2xx response carries meta.api_request_id (req_*) and
        an ISO 8601 api_request_timestamp.
        """
        res = api.create_program(
            create_program_payload(), officer_headers,
        )
        body = res.json()
        assert "meta" in body
        meta = body["meta"]
        # PRD §2.2: "starts with `req_`"
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with req_, got "
            f"{meta['api_request_id']!r}"
        )
        # PRD §2.2: "ISO 8601 UTC timestamp with three fractional digits"
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert "data" in body
        assert body["response_type"] in {"object", "array"}

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: "All error API responses (4xx status codes)
        follow this standard envelope format" with error_id and a
        human-readable message inside data.

        Claim: a 4xx response carries data.error_id and data.message.
        """
        res = api.create_program(create_program_payload(), headers={})
        body = res.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"]


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: list endpoints accept limit (default 10, min 1, max
    100) and offset (default 0); response.meta carries total_count and
    has_more."""

    def test_list_programs_default_pagination(self, api, officer_headers):
        """PRD §2.3: "It defaults to 10, with a minimum of 1 and a
        maximum of 100."

        Claim: GET /programs returns the paginated envelope with
        limit/offset/total_count/has_more in meta.
        """
        res = api.list_programs(officer_headers)
        data, meta = validate_paginated(res)
        assert isinstance(data, list)
        assert "total_count" in meta
        assert "has_more" in meta
        assert "limit" in meta
        assert "offset" in meta


# ===========================================================================
# §2.10 Read-side clock — open endpoint
# ===========================================================================
class TestClockReadOpen:
    """PRD §2.1: "The sole exception is the read-side clock endpoint,
    which is open; the clock-advance endpoint still requires both
    headers." """

    def test_read_clock_without_auth_headers_succeeds(self, api):
        """PRD §2.1: "The sole exception is the read-side clock
        endpoint, which is open."

        Claim: GET /_clock returns 2xx with no auth headers.
        """
        res = api.get_clock()
        # Lenient: it just must not raise auth error. The exact
        # response shape is left to the implementation per PRD §2.10
        # ("A read endpoint exposes the current clock"); we only
        # assert it does not 401.
        assert res.status_code < 400, (
            f"GET /_clock should not require auth, got {res.status_code}"
        )

    def test_clock_advance_requires_auth(self, api):
        """PRD §2.1: "the clock-advance endpoint still requires both
        headers." Therefore POST /_clock/advance without headers is
        rejected with ERR_AUTH_MISSING.

        Claim: POST /_clock/advance with no headers -> ERR_AUTH_MISSING.
        """
        from test_helpers import advance_clock_payload, iso_now
        res = api.advance_clock(
            advance_clock_payload(to_timestamp=iso_now()),
            headers={},
        )
        validate_error(res, "ERR_AUTH_MISSING")
