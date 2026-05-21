"""Auth headers, role validation, ownership, response envelope, pagination.

Covers PRD §2.1 (auth + roles), §2.2 (envelope), §2.3 (pagination),
§2.7 (path validation), §2.9 (validation order: auth precedes existence
precedes state).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_claimant,
    make_claimant_headers,
    setup_application_at_initial_review,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:

    def test_missing_both_headers_returns_auth_required(self, api):
        """PRD §2.1: "A request missing or empty in either header is
        rejected with ERR_AUTH_REQUIRED and HTTP status 401."

        Claim: GET with empty headers -> ERR_AUTH_REQUIRED.
        """
        resp = api._request("GET", "/hearing-slots", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_returns_auth_required(self, api):
        """PRD §2.1: "A request missing or empty in either header is
        rejected with ERR_AUTH_REQUIRED and HTTP status 401."
        """
        resp = api._request(
            "GET", "/hearing-slots",
            headers={"X-User-Role": "PlatformAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_role_returns_auth_required(self, api):
        """PRD §2.1: "A request missing or empty in either header is
        rejected with ERR_AUTH_REQUIRED and HTTP status 401."
        """
        resp = api._request(
            "GET", "/hearing-slots", headers={"X-User-ID": "someone"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_empty_user_id_returns_auth_required(self, api):
        """PRD §2.1: "A request missing or empty in either header is
        rejected with ERR_AUTH_REQUIRED and HTTP status 401."
        """
        resp = api._request(
            "GET", "/hearing-slots",
            headers={"X-User-ID": "", "X-User-Role": "PlatformAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_unknown_role_returns_invalid_role(self, api):
        """PRD §2.1: "A request whose X-User-Role is not one of Claimant,
        DDS_Examiner, ALJ, AppealsCouncil, CDR_Reviewer, or
        PlatformAdmin is rejected with ERR_INVALID_ROLE, also at status
        401."
        """
        resp = api._request(
            "GET", "/hearing-slots",
            headers={"X-User-ID": "anyone", "X-User-Role": "NotARole"},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_ROLE.value)

    @pytest.mark.parametrize("role", [
        "Claimant", "DDS_Examiner", "ALJ",
        "AppealsCouncil", "CDR_Reviewer", "PlatformAdmin",
    ])
    def test_each_recognized_role_clears_auth_gate(self, api, role):
        """PRD §2.1: "A request whose X-User-Role is not one of Claimant,
        DDS_Examiner, ALJ, AppealsCouncil, CDR_Reviewer, or
        PlatformAdmin is rejected with ERR_INVALID_ROLE, also at status
        401."

        Each recognized role must NOT produce ERR_INVALID_ROLE on a
        well-formed request.
        """
        headers = build_user_headers(f"user-{role.lower()}-tst", role)
        # /hearing-slots is GET-listed for ALJ/AppealsCouncil/Claimant/
        # PlatformAdmin, so DDS_Examiner/CDR_Reviewer get ERR_FORBIDDEN
        # — but that is the *next* validation, not ERR_INVALID_ROLE.
        resp = api._request("GET", "/hearing-slots", headers=headers)
        try:
            body = resp.json()
            err = body.get("data", {}).get("error_id") if isinstance(body, dict) else None
        except Exception:
            err = None
        assert err != ApiErrorId.ERR_INVALID_ROLE.value, (
            f"role {role!r} should clear ERR_INVALID_ROLE; got {err}. "
            f"Response: {body}"
        )


class TestRBAC:

    def test_role_not_permitted_on_endpoint_returns_forbidden(self, api):
        """PRD §2.1: "A request whose role is recognised but not
        permitted on the targeted endpoint is rejected with
        ERR_FORBIDDEN at status 403."

        Claim: Claimant cannot create a HearingSlot (ALJ/PlatformAdmin
        only per §4 endpoint table).
        """
        from test_helpers import iso_utc, utcnow
        from datetime import timedelta
        start = utcnow() + timedelta(hours=1)
        end = start + timedelta(minutes=60)
        payload = {
            "alj_id": "alj-X",
            "hearing_office": "OHO_BOSTON",
            "start_at": iso_utc(start),
            "end_at": iso_utc(end),
        }
        resp = api.create_hearing_slot(
            payload, TEST_USERS["claimant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_cross_claimant_access_returns_forbidden(self, api):
        """PRD §2.1: "When X-User-Role is Claimant, the X-User-ID is the
        id of the acting Claimant; ownership checks on any resource that
        references a Claimant compare the resource's claimant_id to
        X-User-ID, and a mismatched claimant in the URL path also yields
        ERR_FORBIDDEN."

        Claim: a Claimant calling GET /claimants/{other_claimant_id}
        gets ERR_FORBIDDEN.
        """
        claimant_a = create_claimant()
        claimant_b = create_claimant()
        # A reads B's record while authenticated as A.
        headers_a = make_claimant_headers(claimant_a["id"])
        resp = api.get_claimant(claimant_b["id"], headers_a)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestEnvelope:

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format ... The
        response_type is either 'object' for a single resource or
        'array' for a list of resources."
        """
        claimant = create_claimant()
        resp = api.get_claimant(
            claimant["id"], TEST_USERS["platform_admin_headers"],
        )
        body = resp.json()
        assert "meta" in body, f"missing meta in response: {body}"
        assert "response_type" in body
        assert body["response_type"] in ("object", "array")
        assert "data" in body
        meta = body["meta"]
        # PRD §2.2: 'api_request_id is a server-generated unique
        # identifier for the request that starts with "req_"'.
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        # PRD §2.2: api_request_timestamp is ISO 8601 UTC.
        assert isinstance(meta.get("api_request_timestamp"), str)

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format ... The error_id is a unique,
        machine-readable string that identifies the specific error."
        """
        resp = api._request("GET", "/hearing-slots", headers={})
        body = resp.json()
        assert body.get("response_type") == "error"
        assert "data" in body
        data = body["data"]
        assert "error_id" in data
        assert "message" in data


class TestPathValidation:

    def test_missing_claimant_returns_claimant_not_found(self, api):
        """PRD §2.7: "A missing Claimant yields ERR_CLAIMANT_NOT_FOUND
        at HTTP status 404."
        """
        resp = api.get_claimant(
            NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CLAIMANT_NOT_FOUND.value)

    def test_missing_application_returns_application_not_found(self, api):
        """PRD §2.7: "A missing Application referenced inside an
        existing claimant's path, or one belonging to a different
        claimant, yields ERR_APPLICATION_NOT_FOUND at status 404."
        """
        claimant = create_claimant()
        resp = api.get_application(
            claimant["id"], NON_EXISTENT_UUID,
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value)

    def test_application_under_wrong_claimant_returns_application_not_found(
        self, api,
    ):
        """PRD §2.7: "A missing Application referenced inside an
        existing claimant's path, or one belonging to a different
        claimant, yields ERR_APPLICATION_NOT_FOUND at status 404."
        """
        claimant_a, application, _ = setup_application_at_initial_review()
        # Make a second claimant and try to read A's application under B.
        claimant_b = create_claimant()
        resp = api.get_application(
            claimant_b["id"], application["id"],
            TEST_USERS["platform_admin_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_APPLICATION_NOT_FOUND.value,
        )

    def test_unknown_resource_returns_resource_not_found(self, api):
        """PRD §2.7: "Any other referenced resource — MedicalEvidence,
        QuarterCredit, HearingSlot, ChildAuxiliary, SSISupplement,
        CDRReview, or a determination identifier — that cannot be
        resolved yields the generic ERR_RESOURCE_NOT_FOUND at status
        404."
        """
        resp = api.book_hearing_slot(
            NON_EXISTENT_UUID,
            {"application_id": NON_EXISTENT_UUID},
            TEST_USERS["alj_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


class TestValidationOrder:

    def test_auth_precedes_existence(self, api):
        """PRD §2.9: "Authentication checks come first ... Existence
        checks follow, in left-to-right path order: claimant existence,
        application existence within the claimant, and finally any
        other addressed resource."

        Probe a path with a missing claimant AND no headers — auth fires
        first, not 404.
        """
        resp = api._request(
            "GET", f"/claimants/{NON_EXISTENT_UUID}", headers={},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


class TestPagination:

    def test_limit_below_minimum_returns_invalid_pagination(self, api):
        """PRD §2.3: "Either parameter outside its permitted range
        produces ERR_INVALID_PAGINATION at HTTP status 422."
        """
        resp = api.list_hearing_slots(
            TEST_USERS["platform_admin_headers"], params={"limit": 0},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_limit_above_maximum_returns_invalid_pagination(self, api):
        """PRD §2.3: "Either parameter outside its permitted range
        produces ERR_INVALID_PAGINATION at HTTP status 422."
        """
        resp = api.list_hearing_slots(
            TEST_USERS["platform_admin_headers"], params={"limit": 101},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_negative_offset_returns_invalid_pagination(self, api):
        """PRD §2.3: "the default offset is 0 and it must be zero or
        greater. Either parameter outside its permitted range produces
        ERR_INVALID_PAGINATION at HTTP status 422."
        """
        resp = api.list_hearing_slots(
            TEST_USERS["platform_admin_headers"], params={"offset": -1},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_limit_one_and_max_are_accepted(self, api):
        """PRD §2.3: "the minimum is 1, and the maximum is 100".

        Boundary: limits at min/max must NOT trigger
        ERR_INVALID_PAGINATION.
        """
        for limit in (1, 100):
            resp = api.list_hearing_slots(
                TEST_USERS["platform_admin_headers"],
                params={"limit": limit},
            )
            data, meta = validate_paginated(resp)
            assert isinstance(data, list)
            assert meta.get("limit") == limit
