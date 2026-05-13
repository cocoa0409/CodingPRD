"""Auth headers, role enforcement, response envelope, pagination,
path-parameter resolution.

PRD §2.1, §2.2, §2.3, §2.6, §2.7.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    SEC,
    WATCHER,
    build_user_headers,
    create_application_payload,
    create_application,
    create_member,
    create_member_payload,
    make_applicant_headers,
    make_committee_member_headers,
    setup_application_pending_review,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth header presence (PRD §2.1)
# ===========================================================================
class TestAuthHeadersRequired:
    """PRD §2.1: 'Every request to the API must carry two case-sensitive
    headers: X-User-ID ... and X-User-Role ... Both headers must be
    present and non-empty; a missing or empty header yields
    ERR_AUTH_MISSING with HTTP 401.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: 'a missing or empty header yields ERR_AUTH_MISSING
        with HTTP 401.'"""
        res = api.list_applications({})
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_rejected(self, api):
        """PRD §2.1: 'a missing or empty header yields ERR_AUTH_MISSING
        with HTTP 401.'"""
        res = api.list_applications({"X-User-Role": "Secretary"})
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_role_rejected(self, api):
        """PRD §2.1: 'a missing or empty header yields ERR_AUTH_MISSING
        with HTTP 401.'"""
        res = api.list_applications({"X-User-ID": "some-id"})
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: 'Both headers must be present and non-empty; a
        missing or empty header yields ERR_AUTH_MISSING with HTTP 401.'"""
        res = api.list_applications({
            "X-User-ID": "", "X-User-Role": "Secretary",
        })
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_role_rejected(self, api):
        """PRD §2.1: 'Both headers must be present and non-empty; a
        missing or empty header yields ERR_AUTH_MISSING with HTTP 401.'"""
        res = api.list_applications({
            "X-User-ID": "x", "X-User-Role": "",
        })
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)


class TestAuthRoleInvalid:
    """PRD §2.1: 'An X-User-Role value outside the declared set yields
    ERR_AUTH_INVALID with HTTP 401.'"""

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: 'An X-User-Role value outside the declared set
        yields ERR_AUTH_INVALID with HTTP 401.'"""
        headers = build_user_headers("u", "GodMode")
        res = api.list_applications(headers)
        validate_error(res, ApiErrorId.ERR_AUTH_INVALID.value)


# ===========================================================================
# RBAC: role not permitted for endpoint (PRD §2.1, §4)
# ===========================================================================
class TestRoleForbidden:
    """PRD §2.1: 'When a caller is authenticated and authorized for the
    endpoint by role but is not the resource owner or not in scope for
    the specific resource, the response is ERR_FORBIDDEN with HTTP 403.'
    Per PRD §4 endpoint catalogue, POST /ethics/applications is
    Applicant only."""

    def test_secretary_cannot_create_application(self, api):
        """PRD §4: POST /ethics/applications is authorized only for
        Applicant; PRD §2.1 forbids other roles."""
        res = api.create_application(create_application_payload(), SEC)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_watcher_cannot_create_application(self, api):
        """PRD §4: POST /ethics/applications is Applicant-only."""
        res = api.create_application(create_application_payload(), WATCHER)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_applicant_cannot_create_member(self, api):
        """PRD §4: POST /ethics/members is Secretary-only."""
        headers = make_applicant_headers("some-pi")
        res = api.create_member(create_member_payload(), headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_watcher_cannot_advance_clock(self, api):
        """PRD §4: POST /ethics/_clock/advance is Secretary-only."""
        res = api.advance_clock(
            {"target_timestamp": "2026-01-01T00:00:00.000Z"},
            WATCHER,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Applicant ownership (PRD §2.1)
# ===========================================================================
class TestApplicantOwnership:
    """PRD §2.1: 'every write action that names a specific application
    ... compares the addressed Application's applicant_id to X-User-ID
    and rejects mismatches with ERR_FORBIDDEN.'"""

    def test_intruder_applicant_cannot_create_submission(self, api):
        """PRD §2.1: 'every write action that names a specific
        application (submitting for pre-screen, uploading a new
        submission version, responding to a rectification, filing an
        annual report) compares the addressed Application's
        applicant_id to X-User-ID and rejects mismatches with
        ERR_FORBIDDEN.'"""
        app, _ = setup_application_pending_review()
        intruder_headers = make_applicant_headers("other-pi-id")
        res = api.create_submission(
            app["id"],
            {
                "protocol_doc_uri": "https://x/p.pdf",
                "investigator_brochure_uri": "https://x/ib.pdf",
                "informed_consent_uri": "https://x/icf.pdf",
                "cv_doc_uri": "https://x/cv.pdf",
            },
            intruder_headers,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_intruder_applicant_cannot_submit_for_prescreen(self, api):
        """PRD §2.1: 'every write action that names a specific
        application (submitting for pre-screen ...) compares the
        addressed Application's applicant_id to X-User-ID and rejects
        mismatches with ERR_FORBIDDEN.'"""
        from test_helpers import create_application_with_submission
        app, _ = create_application_with_submission()
        intruder = make_applicant_headers("other-pi-id")
        res = api.submit_application(app["id"], intruder)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope (PRD §2.2)
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: 'All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body.'"""

    def test_create_application_returns_envelope(self, api):
        """PRD §2.2: standard envelope with meta + response_type + data;
        PRD §4: 'New-resource creation endpoints return HTTP 201.'"""
        headers = make_applicant_headers("pi-env-01")
        res = api.create_application(
            create_application_payload(), headers,
        )
        data = validate_success(res, expected_status=201)
        assert "id" in data and "sponsor_name" in data, (
            f"data must carry the created Application; got {data!r}"
        )

    def test_envelope_has_request_id_and_timestamp(self, api):
        """PRD §2.2: 'The api_request_id is a server-generated unique
        identifier for the request that starts with req_'."""
        res = api.list_applications(SEC)
        assert res.status_code == 200
        body = res.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"PRD §2.2 api_request_id must start with 'req_'; got "
            f"{body['meta']['api_request_id']!r}"
        )
        assert "api_request_timestamp" in body["meta"]


# ===========================================================================
# Path-parameter resolution (PRD §2.6)
# ===========================================================================
class TestNotFound:
    """PRD §2.6: 'URL paths with multiple identifier segments are
    resolved left to right ... if no application of that id exists, the
    response is ERR_NOT_FOUND with HTTP 404.'"""

    def test_get_application_nonexistent_returns_404(self, api):
        """PRD §2.6: 'if no application of that id exists, the response
        is ERR_NOT_FOUND with HTTP 404 and the inner resource is never
        consulted.'"""
        res = api.get_application(NON_EXISTENT_UUID, SEC)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_member_nonexistent_returns_404(self, api):
        """PRD §2.6: path-parameter resolution returns ERR_NOT_FOUND."""
        res = api.get_member(NON_EXISTENT_UUID, SEC)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_meeting_nonexistent_returns_404(self, api):
        """PRD §2.6: path-parameter resolution returns ERR_NOT_FOUND."""
        res = api.get_meeting(NON_EXISTENT_UUID, SEC)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_annual_reports_parent_app_nonexistent_returns_404(self, api):
        """PRD §2.6: 'on the annual-reports listing under an application,
        the path parameter aid names the parent application's id and is
        resolved first; if no application of that id exists, the
        response is ERR_NOT_FOUND with HTTP 404 and the inner resource
        is never consulted.'"""
        res = api.list_annual_reports(NON_EXISTENT_UUID, SEC)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


class TestReferenceNotFound:
    """PRD §2.6: 'Body foreign-key references ... are resolved separately
    and yield ERR_REFERENCE_NOT_FOUND with HTTP 404 if the referenced
    row does not exist.'"""

    def test_create_member_conflict_with_unknown_application_id(self, api):
        """PRD §2.6: body foreign-key references yield
        ERR_REFERENCE_NOT_FOUND."""
        m = create_member()
        res = api.declare_conflict(
            m["id"],
            {"application_id": NON_EXISTENT_UUID,
             "conflict_type": "SPONSOR_RELATION",
             "details": "test"},
            SEC,
        )
        validate_error(res, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Pagination (PRD §2.3)
# ===========================================================================
class TestPagination:
    """PRD §2.3: 'All list endpoints accept two pagination query
    parameters, limit and offset.'"""

    def test_default_pagination_limit_is_10(self, api):
        """PRD §2.3: 'The limit parameter defaults to 10 when omitted.'"""
        res = api.list_applications(SEC)
        data, meta = validate_paginated(res)
        assert meta.get("limit") == 10, (
            f"PRD §2.3 'The limit parameter defaults to 10 when "
            f"omitted'; got {meta.get('limit')!r}"
        )

    def test_default_offset_is_zero(self, api):
        """PRD §2.3: 'The offset parameter defaults to 0 and may not be
        negative.'"""
        res = api.list_applications(SEC)
        data, meta = validate_paginated(res)
        assert meta.get("offset") == 0
