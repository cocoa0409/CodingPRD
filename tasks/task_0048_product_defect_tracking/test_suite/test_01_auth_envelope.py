"""Auth header presence, RBAC permission checks, response envelope shape,
and pagination defaults.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_project_payload,
    setup_team,
    setup_basic_module,
)


class TestUserContextHeaders:
    def test_missing_user_id_header_rejected(self):
        """PRD §2.1: "Both headers must be present and non-empty;
        if either is missing or empty the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
        """
        resp = api_client._request(
            "GET", "/projects", headers={"X-User-Role": "TriageManager"},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_missing_user_role_header_rejected(self):
        """PRD §2.1: "Both headers must be present and non-empty;
        if either is missing or empty the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
        """
        resp = api_client._request(
            "GET", "/projects", headers={"X-User-ID": "alice"},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_empty_user_id_header_rejected(self):
        """PRD §2.1: "Both headers must be present and non-empty;
        if either is missing or empty the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
        """
        resp = api_client._request(
            "GET", "/projects",
            headers={"X-User-ID": "", "X-User-Role": "TriageManager"},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_empty_user_role_header_rejected(self):
        """PRD §2.1: "Both headers must be present and non-empty;
        if either is missing or empty the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."
        """
        resp = api_client._request(
            "GET", "/projects",
            headers={"X-User-ID": "alice", "X-User-Role": ""},
        )
        validate_error(
            resp,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )


class TestRolePermissionRejection:
    def test_developer_cannot_create_project(self, developer_headers_fallback):
        """PRD §2.1: "If the headers are well-formed but the role declared
        does not have permission for the requested operation, the response
        is ERR_INSUFFICIENT_PERMISSIONS."
        PRD §4: "POST /projects" is restricted to TriageManager.
        """
        resp = api_client.create_project(
            create_project_payload(), developer_headers_fallback,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        )

    def test_qa_engineer_cannot_create_project(
        self, qa_engineer_headers_fallback,
    ):
        """PRD §2.1: "If the headers are well-formed but the role declared
        does not have permission for the requested operation, the response
        is ERR_INSUFFICIENT_PERMISSIONS."
        """
        resp = api_client.create_project(
            create_project_payload(), qa_engineer_headers_fallback,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        )

    def test_release_manager_cannot_create_project(
        self, release_manager_headers_fallback,
    ):
        """PRD §2.1: "If the headers are well-formed but the role declared
        does not have permission for the requested operation, the response
        is ERR_INSUFFICIENT_PERMISSIONS."
        """
        resp = api_client.create_project(
            create_project_payload(), release_manager_headers_fallback,
        )
        validate_error(
            resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value,
        )


class TestResponseEnvelope:
    def test_success_envelope_carries_meta_and_data(self):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body".
        The api_request_id starts with 'req_' and api_request_timestamp is
        ISO 8601 UTC.
        """
        team = setup_team()
        # The framework's validate_success already checks the envelope
        # shape (meta + response_type + data) end-to-end. Re-issue a read
        # to assert directly.
        resp = api_client.get_project(team.project["id"], team.triage_headers)
        body = resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        meta = body["meta"]
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id starts with 'req_'"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body["response_type"] == "object"

    def test_paginated_list_meta_fields(self):
        """PRD §2.3: "limit defaults to 10 ... The meta object on a list
        response surfaces four pagination fields: limit, offset,
        total_count ... and has_more (a boolean indicating whether
        offset + limit is less than total_count)."
        """
        team = setup_team()
        resp = api_client.list_projects(team.triage_headers)
        data, meta = validate_paginated(resp)
        assert "limit" in meta and "offset" in meta
        assert "total_count" in meta and "has_more" in meta
        assert meta["limit"] == 10, (
            "PRD §2.3: limit defaults to 10"
        )
        assert meta["offset"] == 0
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)


class TestErrorEnvelope:
    def test_error_envelope_carries_error_id_and_message(self):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format" with data carrying error_id (a
        unique, machine-readable string) and message.
        """
        team = setup_team()
        # Trigger ERR_PROJECT_NOT_FOUND with a non-existent project id.
        resp = api_client.get_project(
            "00000000-0000-0000-0000-000000000000", team.triage_headers,
        )
        body = resp.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]
