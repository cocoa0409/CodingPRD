"""Authentication, envelope, pagination, and path-resolution tests.

Covers PRD §2.1 (headers & roles), §2.2 (envelope), §2.3 (pagination),
§2.5 (hierarchical path resolution).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_candidate,
    create_capacity,
    create_event_with_capacity,
    create_test_event,
    force_confirmed_registration,
    make_candidate_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth header well-formedness and role permission
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_user_id_header_returns_400(self, api):
        """PRD §2.1: "Every request to the API must carry two headers:
        `X-User-ID` and `X-User-Role`. ... Missing or malformed values
        for either header are rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Claim: list-test-events with only X-User-Role yields
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        res = api.list_test_events({"X-User-Role": "Registrar"})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_missing_user_role_header_returns_400(self, api):
        """PRD §2.1: "Missing or malformed values for either header are
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Claim: list-test-events with only X-User-ID yields
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        res = api.list_test_events({"X-User-ID": "anyone"})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_unknown_role_value_is_malformed(self, api):
        """PRD §2.1: "Any other value in `X-User-Role` is treated as if
        the header were malformed."

        Claim: a role string outside the recognised five yields
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        res = api.list_test_events(
            build_user_headers("anyone", "Hacker"),
        )
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)

    def test_role_lacks_permission_returns_403(self, api):
        """PRD §2.1: "A header pair that is well-formed but whose role
        lacks permission for the requested endpoint ... is rejected
        with `ERR_INSUFFICIENT_PERMISSIONS`."

        Claim: Candidate cannot POST /test-events; the call returns
        ERR_INSUFFICIENT_PERMISSIONS.
        """
        # Need a real candidate id so the header is well-formed.
        candidate = create_candidate()
        from test_helpers import create_test_event_payload
        payload = create_test_event_payload()
        res = api.create_test_event(payload, make_candidate_headers(candidate["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_candidate_cannot_read_other_candidates_data(self, api):
        """PRD §3.3: "Attempting to read another candidate's resources
        yields `ERR_INSUFFICIENT_PERMISSIONS`."

        Claim: candidate A reading candidate B's record returns
        ERR_INSUFFICIENT_PERMISSIONS.
        """
        a = create_candidate()
        b = create_candidate()
        res = api.get_candidate(b["id"], make_candidate_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# ===========================================================================
# §2.2 Envelope structure
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: every 2xx response uses the success envelope."""

    def test_success_envelope_has_meta_and_data(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" with `meta`, `response_type`, and `data` fields.

        Claim: a successful create-test-event returns the envelope
        shape with all three keys and api_request_id starting with
        `req_`.
        """
        event = create_test_event()
        # validate_success was already called inside fixtures; re-fetch
        # via GET to inspect the raw envelope.
        res = api.get_test_event(event["id"], TEST_USERS["registrar_headers"])
        data = validate_success(res, 200)
        assert data["id"] == event["id"]
        # The validator already enforced shape; assert the api_request_id format.
        body = res.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id must start with 'req_'"
        )
        assert body["response_type"] == "object"


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: list endpoints accept limit/offset, surface meta."""

    def test_default_pagination_limit_10(self, api):
        """PRD §2.3: "`limit` defaults to 10 when omitted".

        Claim: GET /test-events without params returns meta.limit == 10.
        """
        res = api.list_test_events(TEST_USERS["registrar_headers"])
        _, meta = validate_paginated(res)
        assert meta["limit"] == 10, (
            "PRD §2.3: limit defaults to 10 when omitted"
        )
        assert meta["offset"] == 0
        assert "total_count" in meta
        assert "has_more" in meta

    def test_has_more_flag_true_when_more_pages(self, api):
        """PRD §2.3: "`has_more` is `true` whenever
        `offset + limit < total_count`."

        Claim: with limit=1 and total_count >= 2 the meta.has_more is True.
        """
        # Ensure at least 2 test events.
        create_test_event()
        create_test_event()
        res = api.list_test_events(
            TEST_USERS["registrar_headers"], params={"limit": 1, "offset": 0},
        )
        rows, meta = validate_paginated(res)
        assert len(rows) <= 1
        if meta["total_count"] >= 2:
            assert meta["has_more"] is True

    @pytest.mark.parametrize("bad_limit", [0, 101, 1000])
    def test_limit_out_of_range_rejected(self, api, bad_limit):
        """PRD §2.3: "has a minimum of 1, and a maximum of 100; values
        outside that range are rejected as malformed input."

        Claim: limit=0 or limit=101 returns ERR_INVALID_REQUEST.
        """
        res = api.list_test_events(
            TEST_USERS["registrar_headers"], params={"limit": bad_limit},
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# §2.5 Hierarchical path resolution
# ===========================================================================
class TestHierarchicalPathResolution:
    """PRD §2.5: nested resource paths are validated strictly left-to-right."""

    def test_missing_test_event_returns_test_event_not_found(self, api):
        """PRD §2.5: "A missing `TestEvent` yields
        `ERR_TEST_EVENT_NOT_FOUND`".

        Claim: GET /test-events/{non_existent} returns
        ERR_TEST_EVENT_NOT_FOUND.
        """
        res = api.get_test_event(NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
        validate_error(res, ApiErrorId.ERR_TEST_EVENT_NOT_FOUND.value)

    def test_missing_test_center_returns_test_center_not_found(self, api):
        """PRD §2.5: "a missing `TestCenter` yields
        `ERR_TEST_CENTER_NOT_FOUND`".

        Claim: GET /test-centers/{non_existent} returns
        ERR_TEST_CENTER_NOT_FOUND.
        """
        res = api.get_test_center(NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
        validate_error(res, ApiErrorId.ERR_TEST_CENTER_NOT_FOUND.value)

    def test_missing_candidate_returns_candidate_not_found(self, api):
        """PRD §2.5: "a missing `Candidate` yields
        `ERR_CANDIDATE_NOT_FOUND`".

        Claim: GET /candidates/{non_existent} returns
        ERR_CANDIDATE_NOT_FOUND.
        """
        res = api.get_candidate(NON_EXISTENT_UUID, TEST_USERS["registrar_headers"])
        validate_error(res, ApiErrorId.ERR_CANDIDATE_NOT_FOUND.value)

    def test_missing_registration_returns_registration_not_found(self, api):
        """PRD §2.5: "a missing `Registration` yields
        `ERR_REGISTRATION_NOT_FOUND`".

        Claim: GET /test-events/{event}/registrations/{non_existent}
        on a valid event but unknown registration id returns
        ERR_REGISTRATION_NOT_FOUND.
        """
        event = create_test_event()
        res = api.get_registration(
            event["id"], NON_EXISTENT_UUID, TEST_USERS["registrar_headers"],
        )
        validate_error(res, ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value)

    def test_path_resolution_left_to_right_test_event_first(self, api):
        """PRD §2.5: "The system never short-circuits the order — for
        example, an invalid `registrationId` is never reported until
        both the `testEventId` and the registration's relation to that
        event have been confirmed."

        Claim: when BOTH testEventId and registrationId are unknown,
        the response reports ERR_TEST_EVENT_NOT_FOUND, not
        ERR_REGISTRATION_NOT_FOUND.
        """
        res = api.get_registration(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            TEST_USERS["registrar_headers"],
        )
        validate_error(res, ApiErrorId.ERR_TEST_EVENT_NOT_FOUND.value)
