"""Auth / authorization / not-found / envelope tests (PRD §2.1, §2.2, §2.7).

PRD-faithful negative tests on the universal precedence chain:
ERR_UNAUTHENTICATED -> ERR_FORBIDDEN -> ERR_NOT_FOUND.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    PO,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_design_category_payload,
    create_project_payload,
    setup_on_shelf_project,
    validate_error,
    validate_success,
)


class TestEnvelope:
    """PRD §2.2 — Standard Success / Error response envelopes."""

    def test_success_envelope_has_required_meta_fields(self, api):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body.'
        PRD §2.2: 'The api_request_id is a server-generated unique
        identifier for the request that starts with req_.'

        Claim: a 2xx response carries meta.api_request_id (starting with
        req_) and meta.api_request_timestamp.
        """
        resp = api.list_design_categories(PO)
        body = resp.json()
        assert "meta" in body, "Success envelope must carry meta"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with 'req_'"
        )
        assert "api_request_timestamp" in body["meta"]
        assert "response_type" in body
        assert body["response_type"] in ("object", "array")

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: 'The error_id is a unique, machine-readable string
        that identifies the specific error. The message provides a
        human-readable explanation of what went wrong.'

        Claim: an error response carries data.error_id and data.message.
        """
        resp = api.get_project(NON_EXISTENT_UUID, PO)
        assert 400 <= resp.status_code < 500
        body = resp.json()
        assert body.get("response_type") == "error"
        assert "data" in body
        assert isinstance(body["data"].get("error_id"), str)
        assert isinstance(body["data"].get("message"), str)


class TestAuthentication:
    """PRD §2.1 — missing headers must short-circuit with ERR_UNAUTHENTICATED."""

    def test_missing_user_id_header_unauthenticated(self, api):
        """PRD §2.1: 'A request missing either header is rejected with
        ERR_UNAUTHENTICATED.'

        Claim: requests without X-User-ID return ERR_UNAUTHENTICATED.
        """
        headers = {"X-User-Role": "PlatformOps"}
        resp = api.list_design_categories(headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_header_unauthenticated(self, api):
        """PRD §2.1: 'A request missing either header is rejected with
        ERR_UNAUTHENTICATED.'

        Claim: requests without X-User-Role return ERR_UNAUTHENTICATED.
        """
        headers = {"X-User-ID": "any"}
        resp = api.list_design_categories(headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestAuthorization:
    """PRD §2.1 — role not permitted returns ERR_FORBIDDEN."""

    def test_designer_cannot_create_design_category(self, api):
        """PRD §2.1: 'A request whose role is not permitted to call the
        targeted endpoint is rejected with ERR_FORBIDDEN.'
        PRD §4: 'POST /design-categories — Authorized Role(s): PlatformOps.'

        Claim: non-PlatformOps role is rejected with ERR_FORBIDDEN.
        """
        headers = build_user_headers("designer-impostor", "Designer")
        resp = api.create_design_category(
            create_design_category_payload(), headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_reviewer_cannot_create_project(self, api):
        """PRD §2.1: 'A request whose role is not permitted to call the
        targeted endpoint is rejected with ERR_FORBIDDEN.'
        PRD §4: 'POST /projects — Authorized Role(s): Client.'

        Claim: a Reviewer attempting POST /projects gets ERR_FORBIDDEN.
        """
        headers = build_user_headers("rev-impostor", "Reviewer")
        # Use any payload; role check fires before body validation.
        resp = api.create_project(
            create_project_payload(
                client_id="any",
                category_code="LOGO",
            ),
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestNotFound:
    """PRD §2.7 — left-to-right path resolution returns ERR_NOT_FOUND
    immediately when the first identifier is missing."""

    def test_get_project_unknown_id(self, api):
        """PRD §2.7: 'The first identifier that does not resolve to an
        existing resource produces ERR_NOT_FOUND immediately, before
        any downstream identifier or body field is inspected.'

        Claim: GET on a non-existent project returns ERR_NOT_FOUND.
        """
        resp = api.get_project(NON_EXISTENT_UUID, PO)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_submission_unknown_id(self, api):
        """PRD §2.7: 'The first identifier that does not resolve to an
        existing resource produces ERR_NOT_FOUND immediately, before
        any downstream identifier or body field is inspected.'

        Claim: GET /submissions/{id} on a non-existent id returns
        ERR_NOT_FOUND.
        """
        resp = api.get_submission(NON_EXISTENT_UUID, PO)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


class TestRoleSegregation:
    """PRD §2.1 + §4 — role table — verify several role-exclusive ops."""

    def test_client_cannot_approve_project(self, api):
        """PRD §4: 'POST /projects/{project_id}/approve — Authorized
        Role(s): PlatformOps.'

        Claim: a Client cannot call approve and receives ERR_FORBIDDEN.
        """
        ctx = setup_on_shelf_project()
        # Use Client headers (owner of the project) to make sure ERR_FORBIDDEN
        # is the rejection reason and not ERR_UNAUTHENTICATED.
        client = ctx["client"]
        from test_helpers import make_client_headers
        # The project has already been approved by setup_on_shelf_project.
        # Make a fresh one in UNDER_PLATFORM_REVIEW for this test.
        from test_helpers import setup_project_ready_for_submit
        ctx2 = setup_project_ready_for_submit()
        c2 = ctx2["client"]
        api.submit_project_for_review(
            ctx2["project"]["id"], make_client_headers(c2["id"]),
        )
        resp = api.approve_project(
            ctx2["project"]["id"], make_client_headers(c2["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
