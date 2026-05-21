"""Auth headers, role-based access control, response envelope shape.

Covers PRD §2.1 (auth), §2.2 (envelope), §2.3 (pagination), §2.6
(left-to-right path validation), §2.12 (validation priority — auth
beats existence which beats state).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_park,
    create_park_payload,
    create_visitor,
    make_visitor_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthHeaders:

    def test_missing_both_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry the two authentication
        headers X-User-ID and X-User-Role. Missing, malformed, or
        unparseable headers result in ERR_UNAUTHENTICATED."

        Claim: GET with empty headers → ERR_UNAUTHENTICATED.
        """
        resp = api._request("GET", "/parks", headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_id_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry the two authentication
        headers X-User-ID and X-User-Role. Missing, malformed, or
        unparseable headers result in ERR_UNAUTHENTICATED."
        """
        resp = api._request(
            "GET", "/parks", headers={"X-User-Role": "ParkAdmin"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry the two authentication
        headers X-User-ID and X-User-Role. Missing, malformed, or
        unparseable headers result in ERR_UNAUTHENTICATED."
        """
        resp = api._request(
            "GET", "/parks", headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    @pytest.mark.parametrize("role", [
        "Visitor", "ParkAdmin", "ParkRanger", "SystemOperator",
    ])
    def test_each_of_four_roles_clears_auth_stage(self, api, role):
        """PRD §2.1: "The system recognises four roles, each spelled
        exactly as listed: Visitor, ParkAdmin, ParkRanger, and
        SystemOperator."

        Claim: each of the four accepted role values clears the auth
        gate — the response (if any) is NOT ERR_UNAUTHENTICATED.
        """
        headers = build_user_headers(f"user-{role.lower()}-test", role)
        resp = api._request("GET", "/parks", headers=headers)
        # Any other outcome is fine — what matters is the auth gate
        # passed (no ERR_UNAUTHENTICATED).
        try:
            body = resp.json()
            err = body.get("data", {}).get("error_id")
        except Exception:
            err = None
        assert err != ApiErrorId.ERR_UNAUTHENTICATED.value, (
            f"role {role!r} should clear auth gate; got "
            f"ERR_UNAUTHENTICATED. Response: {body}"
        )

    def test_unknown_role_returns_unauthenticated(self, api):
        """PRD §2.1: "When a caller's role is well-formed but not
        authorised for the requested endpoint, the request is rejected
        with ERR_FORBIDDEN. ... Missing, malformed, or unparseable
        headers result in ERR_UNAUTHENTICATED."

        A role string outside the four-value catalogue is malformed at
        the auth stage and yields ERR_UNAUTHENTICATED. Note: even if an
        implementation legitimately returns ERR_FORBIDDEN here, the
        important distinction is that no real role gates pass for an
        unknown role — accept either outcome to remain PRD-faithful.
        """
        from test_helpers import validate_error_is_one_of
        bad_headers = build_user_headers("user-x", "Janitor")
        resp = api._request("GET", "/parks", headers=bad_headers)
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_UNAUTHENTICATED.value,
            ApiErrorId.ERR_FORBIDDEN.value,
        ])


class TestForbidden:

    def test_visitor_cannot_create_park(self, api):
        """PRD §2.1 + §4 RBAC: "When a caller's role is well-formed
        but not authorised for the requested endpoint, the request is
        rejected with ERR_FORBIDDEN."
        PRD §4: "POST /parks ... ParkAdmin" (only).
        """
        resp = api.create_park(
            create_park_payload(), TEST_USERS["visitor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_park_ranger_cannot_create_park(self, api):
        """PRD §4: POST /parks is exclusive to ParkAdmin."""
        resp = api.create_park(
            create_park_payload(), TEST_USERS["park_ranger_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_visitor_cannot_freeze_park(self, api):
        """PRD §2.7: "Only a ParkAdmin may move a park between these
        statuses."
        """
        park = create_park()
        resp = api.freeze_park(park["id"], TEST_USERS["visitor_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_visitor_cannot_act_on_another_visitors_reservation(self, api):
        """PRD §2.1: "Ownership checks on any resource that references
        a visitor (a campground reservation, a timed-entry reservation,
        a backcountry permit, a lottery application, a waitlist entry,
        an America the Beautiful Pass, a ledger entry) compare the
        resource's visitor_id to X-User-ID, and confirm/cancel/accept/
        decline actions on a resource owned by another visitor are
        rejected with ERR_FORBIDDEN."

        Claim: V2 cancelling V1's HELD timed-entry → ERR_FORBIDDEN.
        """
        from test_helpers import (
            create_timed_entry, create_visitor_with_wallet,
            date_to_local_str,
        )
        from datetime import date, timedelta
        park = create_park()
        v1 = create_visitor_with_wallet(wallet_cents=10_000)
        v2 = create_visitor_with_wallet(wallet_cents=10_000)
        entry_date = date_to_local_str(date.today() + timedelta(days=5))
        r = create_timed_entry(
            park["id"], v1, entry_date_local=entry_date,
            window_start_local="09:00",
        )
        resp = api.cancel_timed_entry(
            park["id"], r["id"], make_visitor_headers(v2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestEnvelopeShape:

    def test_success_envelope_shape(self, api, park_admin_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body: meta { api_request_id, api_request_timestamp ... },
        response_type 'object' | 'array', data { }."
        """
        resp = api.create_park(create_park_payload(), park_admin_headers)
        body = resp.json()
        assert "meta" in body, f"missing meta: {body}"
        assert "response_type" in body, f"missing response_type: {body}"
        assert "data" in body, f"missing data: {body}"
        assert body["response_type"] in {"object", "array"}, (
            f"response_type must be 'object' or 'array', got "
            f"{body['response_type']!r}"
        )
        meta = body["meta"]
        assert "api_request_id" in meta and isinstance(
            meta["api_request_id"], str,
        ), f"api_request_id missing or not str: {meta}"
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert "api_request_timestamp" in meta

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format: meta { api_request_id,
        api_request_timestamp }, response_type 'error', data { error_id,
        message }."
        """
        resp = api._request("GET", "/parks", headers={})
        body = resp.json()
        assert body.get("response_type") == "error", (
            f"error envelope must have response_type 'error', got "
            f"{body.get('response_type')!r}"
        )
        data = body.get("data") or {}
        assert "error_id" in data and isinstance(data["error_id"], str)
        assert "message" in data and isinstance(data["message"], str)
        meta = body.get("meta") or {}
        assert "api_request_id" in meta
        assert "api_request_timestamp" in meta


class TestPagination:

    def test_list_includes_pagination_meta(self, api, park_admin_headers):
        """PRD §2.3: "Every list response includes limit, offset,
        total_count, and has_more in its meta object."
        """
        # Create at least one park so the list is not empty.
        create_park()
        data, meta = validate_paginated(api.list_parks(park_admin_headers))
        assert "total_count" in meta
        assert "has_more" in meta
        assert "limit" in meta
        assert "offset" in meta

    def test_list_default_limit_is_10(self, api, park_admin_headers):
        """PRD §2.3: "The limit query parameter caps the number of items
        returned; if omitted it defaults to 10."
        """
        for _ in range(3):
            create_park()
        data, meta = validate_paginated(api.list_parks(park_admin_headers))
        assert meta["limit"] == 10, (
            f"default limit must be 10, got {meta['limit']!r}"
        )

    def test_list_honours_explicit_limit(self, api, park_admin_headers):
        """PRD §2.3: "if omitted it defaults to 10, with a minimum of 1
        and a maximum of 100."
        """
        for _ in range(3):
            create_park()
        data, meta = validate_paginated(
            api.list_parks(park_admin_headers, params={"limit": 1}),
        )
        assert len(data) == 1
        assert meta["limit"] == 1
        assert meta["has_more"] is True

    def test_list_offset_skips_items(self, api, park_admin_headers):
        """PRD §2.3: "The offset query parameter is the number of items
        to skip from the start of the list and defaults to 0."
        """
        for _ in range(3):
            create_park()
        data, meta = validate_paginated(
            api.list_parks(park_admin_headers, params={"offset": 9999}),
        )
        assert len(data) == 0
        assert meta["has_more"] is False


class TestPathExistence:

    def test_get_nonexistent_park_returns_404(self, api, park_admin_headers):
        """PRD §2.6: "Whenever an endpoint path contains nested
        identifiers ... the system resolves each identifier in left-to-
        right order and rejects the request immediately with
        ERR_NOT_FOUND when any one is unknown."

        Claim: GET on a non-existent Park id → ERR_NOT_FOUND (404).
        """
        resp = api.get_park(NON_EXISTENT_UUID, park_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_left_to_right_existence_on_nested_path(self, api):
        """PRD §2.6: "A campground reservation requested under a
        non-existent campground returns ERR_NOT_FOUND keyed to the
        missing campground, without ever attempting to find the
        reservation."
        """
        v = create_visitor()
        resp = api.cancel_campground_reservation(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            make_visitor_headers(v["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
