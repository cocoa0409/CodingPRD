"""Platform-wide baseline: response envelopes, pagination, project defaults,
authentication, and role-based access control (PRD §2.1–§2.3, §2.10)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    ApiErrorId,
    ANONYMOUS_HEADERS,
    assert_construction_project,
    create_project_payload,
    create_ld_assessment,
    create_project,
    set_clock,
)


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success(self, api, pce_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." The same section defines
        `response_type` as either "object" for a single resource or "array" for
        a list of resources.

        Design: Corner/endpoints/response_envelope_shape_on_success
        """
        set_clock()
        resp = api.create_project(create_project_payload(), pce_headers)
        assert resp.status_code == 201
        body = resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id must start with req_"
        )
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        assert body["response_type"] == "object"
        assert_construction_project(body["data"])

    def test_error_envelope_shape(self, api, claims_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/error_envelope_shape
        """
        set_clock()
        resp = api.get_project(NON_EXISTENT_UUID, claims_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


class TestProjectResource:
    def test_get_project_not_found(self, api, claims_headers):
        """PRD §2.6: "the system validates existence sequentially from left to right
        and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first
        identifier that does not resolve to an existing resource."

        Design: Corner/entities/get_project_not_found
        """
        set_clock()
        resp = api.get_project(NON_EXISTENT_UUID, claims_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_project_creation_applies_defaults(self, api, pce_headers):
        """PRD §3.1: "The contract's `float_ownership_policy` and `notice_window_days`
        may be supplied at creation; when omitted they default to `CONTRACTOR_OWNS`
        and twenty-one days respectively, per §2.10."
        PRD §3.1: "A new project begins in `PRECONSTRUCTION`."

        Design: Corner/entities/project_creation_applies_defaults
        """
        set_clock()
        resp = api.create_project(
            create_project_payload(),  # omits float_ownership_policy and notice_window_days
            pce_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["float_ownership_policy"] == "CONTRACTOR_OWNS", (
            "omitted float_ownership_policy must default to CONTRACTOR_OWNS"
        )
        assert data["notice_window_days"] == 21, (
            "omitted notice_window_days must default to 21"
        )
        assert data["status"] == "PRECONSTRUCTION"
        assert isinstance(data["version"], int) and data["version"] >= 1

    def test_list_projects_pagination_defaults(self, api, pce_headers):
        """PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter specifies the number of items to skip
        and defaults to 0." and "Paginated and non-paginated list-based responses
        include the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_projects_pagination_defaults
        """
        for name in ("P1", "P2", "P3"):
            create_project(project_name=name)
        resp = api.list_projects(pce_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(meta["api_request_id"], str)
        assert isinstance(meta["api_request_timestamp"], str)
        assert meta["limit"] == 10, "default limit must be 10"
        assert meta["offset"] == 0, "default offset must be 0"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3


class TestAccessControl:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "A request with missing or malformed identity headers is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        set_clock()
        resp = api.create_project(create_project_payload(), ANONYMOUS_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_owner_cannot_create_project(self, api, owner_headers):
        """PRD §2.1: "A `ProjectControlsEngineer` creates projects, activates them,
        and reviews and accepts or rejects schedule versions and progress updates."
        PRD §2.1: "A request whose role is not authorized for the operation is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/owner_cannot_create_project
        """
        set_clock()
        resp = api.create_project(create_project_payload(), owner_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_any_role_can_get(self, api, pce_headers, claims_headers):
        """PRD §2.1: "A sixth designation, `Any`, appears throughout this document
        as a shorthand meaning that every authenticated role may call read-only
        endpoints."

        Design: Corner/rbac/any_role_can_get
        """
        project = create_project()
        resp = api.get_project(project["id"], claims_headers)
        data = validate_success(resp, expected_status=200)
        assert data["id"] == project["id"]

    def test_contractor_cannot_assess_ld(self, api, contractor_headers):
        """PRD §2.1: "An `OwnerRepresentative` reviews extension-of-time requests,
        issues acceleration directives, assesses liquidated damages, and declares
        substantial completion."
        PRD §2.1: "A request whose role is not authorized for the operation is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/contractor_cannot_assess_ld
        """
        project = create_project(
            contract_start_date="2026-04-01T00:00:00Z",
            contract_completion_date="2026-05-01T00:00:00Z",
        )
        lda = create_ld_assessment(project["id"])
        resp = api.assess_ld_assessment(project["id"], lda["id"], contractor_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
