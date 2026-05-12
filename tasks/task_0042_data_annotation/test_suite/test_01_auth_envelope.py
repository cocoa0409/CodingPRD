"""Authentication, RBAC, response envelope, pagination, and nested path
existence checks. Covers PRD §2.1, §2.2, §2.3, §2.8, §2.9."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_project_payload,
    setup_open_project,
    validate_error,
    validate_paginated,
    validate_success,
)


# =========================================================================
# §2.1 -- Headers must be present and non-empty.
# =========================================================================
class TestMissingAuthHeaders:

    def test_missing_user_id_header(self, api):
        """PRD §2.1: 'A request missing either header -- or carrying an
        empty value for either -- is rejected with ERR_MISSING_AUTH_HEADERS.'

        Claim: missing X-User-ID -> ERR_MISSING_AUTH_HEADERS / 400.
        """
        bad = {"X-User-Role": "ProjectManager"}
        res = api._request(
            "POST", "/annotation-projects",
            create_project_payload(), bad,
        )
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    def test_missing_user_role_header(self, api):
        """PRD §2.1: 'A request missing either header -- or carrying an
        empty value for either -- is rejected with ERR_MISSING_AUTH_HEADERS.'

        Claim: missing X-User-Role -> ERR_MISSING_AUTH_HEADERS / 400.
        """
        bad = {"X-User-ID": "pm-001"}
        res = api._request("GET", "/annotation-projects", headers=bad)
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    def test_empty_user_id_header(self, api):
        """PRD §2.1: 'A request missing either header -- or carrying an
        empty value for either -- is rejected with ERR_MISSING_AUTH_HEADERS.'

        Claim: empty X-User-ID -> ERR_MISSING_AUTH_HEADERS / 400.
        """
        bad = {"X-User-ID": "", "X-User-Role": "ProjectManager"}
        res = api._request("GET", "/annotation-projects", headers=bad)
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

    def test_empty_user_role_header(self, api):
        """PRD §2.1: 'A request missing either header -- or carrying an
        empty value for either -- is rejected with ERR_MISSING_AUTH_HEADERS.'

        Claim: empty X-User-Role -> ERR_MISSING_AUTH_HEADERS / 400.
        """
        bad = {"X-User-ID": "pm-001", "X-User-Role": ""}
        res = api._request("GET", "/annotation-projects", headers=bad)
        validate_error(res, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)


# =========================================================================
# §2.1 -- RBAC: role-not-authorised yields ERR_INSUFFICIENT_PERMISSIONS.
# =========================================================================
class TestRoleAuthorization:

    def test_qa_reviewer_cannot_create_project(self, api, qa_reviewer_headers):
        """PRD §2.1: 'A request whose X-User-Role is not authorised to
        perform the requested operation per the §4 endpoint table is
        rejected with ERR_INSUFFICIENT_PERMISSIONS.'

        PRD §4: POST /annotation-projects is authorised only to ProjectManager.

        Claim: QAReviewer attempting POST /annotation-projects -> 403
        ERR_INSUFFICIENT_PERMISSIONS.
        """
        res = api.create_project(create_project_payload(), qa_reviewer_headers)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_annotator_cannot_create_project(
        self, api, annotator_headers_fallback,
    ):
        """PRD §2.1: 'A request whose X-User-Role is not authorised to
        perform the requested operation per the §4 endpoint table is
        rejected with ERR_INSUFFICIENT_PERMISSIONS.'

        PRD §4: POST /annotation-projects is authorised only to ProjectManager.

        Claim: Annotator attempting POST /annotation-projects -> 403.
        """
        res = api.create_project(
            create_project_payload(), annotator_headers_fallback,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_qa_reviewer_cannot_register_annotator(
        self, api, qa_reviewer_headers,
    ):
        """PRD §4: POST /annotators is authorised only to ProjectManager.
        PRD §2.1: 'A request whose X-User-Role is not authorised to perform
        the requested operation per the §4 endpoint table is rejected with
        ERR_INSUFFICIENT_PERMISSIONS.'

        Claim: QAReviewer attempting POST /annotators -> 403.
        """
        res = api.create_annotator({
            "display_name": "X",
            "domain_tags": [],
            "entry_test_score": 50,
        }, qa_reviewer_headers)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# =========================================================================
# §2.2 -- Success envelope structure.
# =========================================================================
class TestSuccessEnvelope:

    def test_create_project_returns_object_envelope(
        self, api, project_manager_headers,
    ):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format'; the response carries
        meta.api_request_id starting with req_, meta.api_request_timestamp,
        response_type, and data.

        Claim: POST /annotation-projects 201 returns the envelope.
        """
        res = api.create_project(
            create_project_payload(), project_manager_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "DRAFT"
        body = res.json()
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id must start with req_"
        )

    def test_list_projects_returns_array_envelope(
        self, api, project_manager_headers,
    ):
        """PRD §2.2: response_type is 'array' for a list of resources.
        PRD §2.3: pagination fields (limit, offset, total_count, has_more)
        appear in meta for list endpoints.

        Claim: GET /annotation-projects returns paginated envelope.
        """
        res = api.list_projects(project_manager_headers)
        data, meta = validate_paginated(res)
        assert isinstance(data, list)
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta


# =========================================================================
# §2.3 -- Pagination.
# =========================================================================
class TestPagination:

    @pytest.mark.parametrize("bad_limit", [0, -1, 101, 200])
    def test_invalid_limit_rejected(
        self, api, project_manager_headers, bad_limit,
    ):
        """PRD §2.3: 'Any request whose limit falls outside the closed
        interval from 1 to 100, or whose offset is negative, is rejected
        with ERR_INVALID_PAGINATION.'

        Claim: limit outside [1,100] -> ERR_INVALID_PAGINATION / 400.
        """
        res = api.list_projects(
            project_manager_headers, params={"limit": bad_limit},
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PAGINATION.value)

    @pytest.mark.parametrize("bad_offset", [-1, -100])
    def test_negative_offset_rejected(
        self, api, project_manager_headers, bad_offset,
    ):
        """PRD §2.3: 'Any request whose limit falls outside the closed
        interval from 1 to 100, or whose offset is negative, is rejected
        with ERR_INVALID_PAGINATION.'

        Claim: negative offset -> ERR_INVALID_PAGINATION / 400.
        """
        res = api.list_projects(
            project_manager_headers, params={"offset": bad_offset},
        )
        validate_error(res, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_limit_boundary_inclusive_one(
        self, api, project_manager_headers,
    ):
        """PRD §2.3: 'The default limit is 10; the minimum is 1; the
        maximum is 100.'

        Claim: limit=1 succeeds.
        """
        res = api.list_projects(
            project_manager_headers, params={"limit": 1},
        )
        validate_paginated(res)

    def test_limit_boundary_inclusive_hundred(
        self, api, project_manager_headers,
    ):
        """PRD §2.3: 'The default limit is 10; the minimum is 1; the
        maximum is 100.'

        Claim: limit=100 succeeds.
        """
        res = api.list_projects(
            project_manager_headers, params={"limit": 100},
        )
        validate_paginated(res)


# =========================================================================
# §2.8 -- Path-resolution existence checks (left-to-right).
# =========================================================================
class TestPathExistence:

    def test_get_project_unknown_id_returns_project_not_found(
        self, api, project_manager_headers,
    ):
        """PRD §2.8: 'Project, annotator, appeal, payroll-period, and
        golden-sample existence likewise produce ERR_PROJECT_NOT_FOUND,
        ERR_ANNOTATOR_NOT_FOUND, ERR_APPEAL_NOT_FOUND,
        ERR_PERIOD_NOT_FOUND, and ERR_GOLDEN_NOT_FOUND respectively.'

        Claim: GET /annotation-projects/{unknown} -> 404 ERR_PROJECT_NOT_FOUND.
        """
        res = api.get_project(NON_EXISTENT_UUID, project_manager_headers)
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_FOUND.value)

    def test_get_annotator_unknown_id(self, api, project_manager_headers):
        """PRD §2.8: existence checks produce ERR_ANNOTATOR_NOT_FOUND for
        an annotator id that does not resolve.

        Claim: GET /annotators/{unknown} -> 404 ERR_ANNOTATOR_NOT_FOUND.
        """
        res = api.get_annotator(NON_EXISTENT_UUID, project_manager_headers)
        validate_error(res, ApiErrorId.ERR_ANNOTATOR_NOT_FOUND.value)

    def test_get_package_unknown_id(self, api, project_manager_headers):
        """PRD §2.8: existence checks produce ERR_PACKAGE_NOT_FOUND for a
        package id that does not resolve.

        Claim: GET /task-packages/{unknown} -> 404 ERR_PACKAGE_NOT_FOUND.
        """
        res = api.get_package(NON_EXISTENT_UUID, project_manager_headers)
        validate_error(res, ApiErrorId.ERR_PACKAGE_NOT_FOUND.value)

    def test_get_appeal_unknown_id(self, api, project_manager_headers):
        """PRD §2.8: existence checks produce ERR_APPEAL_NOT_FOUND for an
        appeal id that does not resolve.

        Claim: GET /appeals/{unknown} -> 404 ERR_APPEAL_NOT_FOUND.
        """
        res = api.get_appeal(NON_EXISTENT_UUID, project_manager_headers)
        validate_error(res, ApiErrorId.ERR_APPEAL_NOT_FOUND.value)

    def test_finalize_unknown_project_returns_project_not_found(
        self, api, qa_reviewer_headers,
    ):
        """PRD §2.8: 'a request to /annotation-projects/{projectId}/
        task-packages/{packageId}/inspections/{inspectionId}/finalize
        validates the project id first and rejects with
        ERR_PROJECT_NOT_FOUND if it does not resolve.'

        Note: finalize lives on /task-packages/{id}/inspections/.../finalize
        so the package id is validated first per PRD §2.8 ordering. We
        therefore assert ERR_PACKAGE_NOT_FOUND on a bad packageId.

        Claim: finalize with unknown packageId -> 404 ERR_PACKAGE_NOT_FOUND.
        """
        res = api.finalize_inspection(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            {"outcome": "PASS", "defects_found": 0},
            qa_reviewer_headers,
        )
        validate_error(res, ApiErrorId.ERR_PACKAGE_NOT_FOUND.value)
