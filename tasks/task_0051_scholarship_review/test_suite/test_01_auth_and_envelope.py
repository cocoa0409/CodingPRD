"""Authentication, RBAC, response envelope, and path-existence checks."""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_application_payload,
    create_disbursement_plan_payload,
    create_open_scholarship,
    create_reviewer_payload,
    create_scholarship_payload,
    is_iso8601_timestamp,
    make_student_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthMissing:
    """PRD §2.1: 'When either header is absent or empty, the request is
    rejected with ERR_AUTH_MISSING (HTTP 401).'"""

    @pytest.mark.parametrize("missing", ["X-User-ID", "X-User-Role"])
    def test_missing_header_returns_auth_missing(self, missing):
        """PRD §2.1: "When either header is absent or empty, the request
        is rejected with ERR_AUTH_MISSING (HTTP 401)."

        Claim: missing X-User-ID or X-User-Role -> ERR_AUTH_MISSING / 401.
        """
        headers = dict(ADMIN)
        headers.pop(missing, None)
        resp = api_client._request(
            "POST", "/scholarships",
            create_scholarship_payload(), headers,
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    @pytest.mark.parametrize("missing", ["X-User-ID", "X-User-Role"])
    def test_empty_header_returns_auth_missing(self, missing):
        """PRD §2.1: "When either header is absent or empty, the request
        is rejected with ERR_AUTH_MISSING (HTTP 401)."

        Claim: empty header value also triggers ERR_AUTH_MISSING.
        """
        headers = dict(ADMIN)
        headers[missing] = ""
        resp = api_client._request(
            "POST", "/scholarships",
            create_scholarship_payload(), headers,
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


class TestForbidden:
    """PRD §2.1: 'When the supplied role is well-formed but is not
    authorised for the requested endpoint per the endpoint table in §4,
    the request is rejected with ERR_FORBIDDEN (HTTP 403).'"""

    def test_student_cannot_create_scholarship(self):
        """PRD §4: "POST /scholarships ... Authorized Role(s) ...
        SchoolAdmin".
        PRD §2.1: "the request is rejected with ERR_FORBIDDEN (HTTP 403)".

        Claim: Student role on POST /scholarships -> ERR_FORBIDDEN.
        """
        resp = api_client.create_scholarship(
            create_scholarship_payload(),
            TEST_USERS["student_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_student_cannot_create_reviewer(self):
        """PRD §4: "POST /reviewers ... SchoolAdmin".

        Claim: Student role -> ERR_FORBIDDEN on POST /reviewers.
        """
        resp = api_client.create_reviewer(
            create_reviewer_payload(),
            TEST_USERS["student_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_reviewer_cannot_create_application(self):
        """PRD §4: "POST /scholarships/{scholarshipId}/applications ...
        Student".

        Claim: Reviewer role -> ERR_FORBIDDEN on POST application.
        """
        sch, _ = create_open_scholarship()
        resp = api_client.create_application(
            sch["id"],
            create_application_payload(),
            TEST_USERS["reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_student_cannot_create_disbursement_plan(self):
        """PRD §4: "POST /scholarships/{id}/disbursement-plans ...
        FinanceOfficer".

        Claim: Student role -> ERR_FORBIDDEN on disbursement plan create.
        """
        sch, _ = create_open_scholarship()
        resp = api_client.create_disbursement_plan(
            sch["id"],
            create_disbursement_plan_payload(),
            TEST_USERS["student_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestNotFound:
    """PRD §2.5: 'the server first verifies that a Scholarship with that
    id exists. If not, the request is rejected with ERR_NOT_FOUND (HTTP
    404) before any further validation runs.'"""

    def test_get_scholarship_unknown_id(self):
        """PRD §2.5: "the server first verifies that a Scholarship with
        that id exists. If not, the request is rejected with
        ERR_NOT_FOUND (HTTP 404) before any further validation runs."

        Claim: GET /scholarships/<unknown> -> ERR_NOT_FOUND.
        """
        resp = api_client.get_scholarship(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_application_under_wrong_scholarship_is_not_found(self):
        """PRD §2.5: "If a deeper segment such as /applications/{applicationId}
        follows, the server verifies that an Application with that id
        exists and that its scholarship_id equals the parent scholarshipId
        from the URL; either failure yields ERR_NOT_FOUND."

        Claim: getting an application via a wrong parent scholarship id
        returns ERR_NOT_FOUND, not a mismatch error.
        """
        # Build a real application under scholarship A.
        sch_a, _ = create_open_scholarship()
        sid = "student-mismatch"
        headers = make_student_headers(sid)
        app = validate_success(
            api_client.create_application(
                sch_a["id"], create_application_payload(), headers,
            ),
            expected_status=201,
        )
        # Build a different scholarship B.
        sch_b, _ = create_open_scholarship(
            application_window_start="2026-08-01T00:00:00Z",
            application_window_end="2026-08-30T00:00:00Z",
            announcement_window_end="2026-09-15T00:00:00Z",
        )
        # Try fetching app via wrong parent.
        resp = api_client.get_application(sch_b["id"], app["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestSuccessEnvelope:
    """PRD §2.2: standard success envelope shape and pagination meta."""

    def test_success_envelope_shape_on_create(self):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body'
        with meta.api_request_id, meta.api_request_timestamp,
        response_type and data.

        Claim: POST /scholarships returns envelope with required meta
        fields.
        """
        resp = api_client.create_scholarship(
            create_scholarship_payload(), ADMIN,
        )
        body = resp.json()
        assert "meta" in body
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id 'starts with req_'"
        )
        assert is_iso8601_timestamp(
            body["meta"].get("api_request_timestamp", "")
        )
        assert body.get("response_type") in {"object", "array"}
        assert "data" in body

    def test_list_envelope_carries_pagination_meta(self):
        """PRD §2.3: 'The meta object of a list response includes limit,
        offset, total_count, and has_more.'

        Claim: list endpoints return limit / offset / total_count /
        has_more in meta.
        """
        sch, _ = create_open_scholarship()
        data, meta = validate_paginated(
            api_client.list_quota_allocations(sch["id"], ADMIN)
        )
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta, f"Pagination meta missing {k}"
        assert isinstance(meta["limit"], int)
        assert isinstance(meta["offset"], int)
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)
