"""Corner — endpoints, errors, and rbac sections.

Pagination, success-envelope shape, error-envelope shape,
reference-not-found, RBAC denials.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    is_iso8601_timestamp,
    set_clock,
    create_chapter,
    create_round,
    register_pnm,
    create_party,
    register_pnm_payload,
    create_chapter_payload,
    create_invitation_payload,
    make_chapter_officer_headers,
    make_pnm_headers,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
)


class TestPaginationPnmsListTotalCountHasMore:
    """3 PNMs registered; limit=2 page-1 returns has_more=true, page-2
    (offset=2) has_more=false."""

    def test_first_page_returns_total_count_3_has_more_true(self, api):
        """PRD §2.3: "The pagination block in `meta` reports `limit`, `offset`, `total_count` (the total number of rows matching the filter, ignoring the slice), and `has_more` (true when `offset + limit < total_count`)."

        Design: Corner/endpoints/corner_pagination_pnms_list_total_count_has_more
        """
        register_pnm(full_name="A", gpa=3.50)
        register_pnm(full_name="B", gpa=3.50)
        register_pnm(full_name="C", gpa=3.50)
        res = api.list_pnms(
            TEST_USERS["panhellenic_admin_headers"], params={"limit": 2, "offset": 0}
        )
        data, meta = validate_paginated(res)
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert len(data) == 2

    def test_second_page_offset_2_returns_has_more_false(self, api):
        """PRD §2.3: "`has_more` (true when `offset + limit < total_count`)."

        Design: Corner/endpoints/corner_pagination_pnms_list_total_count_has_more
        """
        register_pnm(full_name="A", gpa=3.50)
        register_pnm(full_name="B", gpa=3.50)
        register_pnm(full_name="C", gpa=3.50)
        res = api.list_pnms(
            TEST_USERS["panhellenic_admin_headers"], params={"limit": 2, "offset": 2}
        )
        data, meta = validate_paginated(res)
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 1


class TestResponseEnvelopeSuccessShape:
    """Success responses carry meta {api_request_id, api_request_timestamp},
    response_type, data per PRD §2.2."""

    def test_create_chapter_success_envelope_has_required_keys(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body"
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."

        Design: Corner/endpoints/corner_response_envelope_success_shape
        """
        res = api.create_chapter(
            create_chapter_payload(
                name="EnvShape",
                greek_type="FRATERNITY",
                quota_total=2,
                dues_per_member_cents=5000,
                legacy_priority_slots=0,
            ),
            TEST_USERS["panhellenic_admin_headers"],
        )
        assert res.status_code == 201
        body = res.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        assert body["response_type"] == "object"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))


class TestErrorEnvelopeShapeOn404:
    """Error responses carry data {error_id, message} and response_type='error'."""

    def test_get_nonexistent_party_returns_error_envelope_with_error_id_and_message(
        self, api
    ):
        """PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/corner_error_envelope_shape_on_404
        """
        res = api.get_party(
            NON_EXISTENT_UUID, TEST_USERS["panhellenic_admin_headers"]
        )
        assert res.status_code == 404
        body = res.json()
        assert body.get("response_type") == "error"
        data = body.get("data", {})
        assert data.get("error_id") == "ERR_RESOURCE_NOT_FOUND"
        assert isinstance(data.get("message"), str)
        assert len(data["message"]) > 0


class TestErrorReferenceNotFoundOnInvitationCreate:
    """POST /invitations with real party_id but bogus pnm_id returns 422
    ERR_REFERENCE_NOT_FOUND, not 404."""

    def test_invitation_create_with_unresolved_pnm_id_returns_reference_not_found(
        self, api
    ):
        """PRD §2.6: "Foreign-key ids supplied in request bodies (any of `chapter_id`, `pnm_id`, `party_id`, `round_id`, `bid_match_id`, or the optional `legacy_chapter_id`) that do not resolve to an existing row are rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422)."

        Design: Corner/errors/corner_error_reference_not_found_on_invitation_create
        """
        set_clock("2026-09-01T00:00:00Z")
        ch = create_chapter(
            name="RefNF",
            greek_type="FRATERNITY",
            quota_total=2,
            dues_per_member_cents=5000,
            legacy_priority_slots=0,
        )
        rnd = create_round(cycle_label="Fall 2026 rnf")
        party = create_party(
            rnd["id"],
            ch["id"],
            scheduled_start_utc="2026-09-05T18:00:00Z",
            duration_minutes=60,
            capacity=5,
        )
        res = api.create_invitation(
            create_invitation_payload(party["id"], NON_EXISTENT_UUID),
            make_chapter_officer_headers(ch["id"]),
        )
        validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND)


class TestRbacPnmCannotCreateChapter:
    """POST /chapters is exclusive to PanhellenicAdmin; PNM gets 403."""

    def test_pnm_creating_chapter_returns_unauthorized(self, api):
        """PRD §2.1: "A request that is authenticated but whose role is not authorized for the endpoint (per the §4 authorization column) is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/corner_rbac_pnm_cannot_create_chapter
        """
        pnm = register_pnm(full_name="RbacP", gpa=3.50)
        res = api.create_chapter(
            create_chapter_payload(
                name="Forbidden",
                greek_type="SORORITY",
                quota_total=2,
                dues_per_member_cents=1,
                legacy_priority_slots=0,
            ),
            make_pnm_headers(pnm["id"]),
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED)


class TestAuthMissingReturnsUnauthenticated:
    """A non-public endpoint called with no auth headers returns 401."""

    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every non-public request authenticates by carrying two HTTP headers: `X-User-ID`, the caller's identifier, and `X-User-Role`, the caller's role. A request with either header missing or malformed is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/corner_auth_missing_returns_unauthenticated
        """
        res = api.list_rounds(headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)
