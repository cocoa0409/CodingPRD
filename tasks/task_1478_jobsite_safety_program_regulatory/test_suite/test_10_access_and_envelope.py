"""Cross-cutting access control, not-found typing, and list envelope behavior:
auth headers, role denials, auditor read-only posture, pagination, and filters
(PRD §2.1, §2.2, §2.3, §2.9, §2.10)."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, api_client,
    validate_error, validate_success, validate_paginated,
    create_project, create_plan, activate_plan, create_worker,
    complete_orientation, create_subcontractor, set_clock,
    make_safety_manager_headers, make_site_superintendent_headers,
    make_subcontractor_rep_headers, make_compliance_auditor_headers,
)

SM = make_safety_manager_headers()
SS = make_site_superintendent_headers()
AUDITOR = make_compliance_auditor_headers()


class TestAuthHeaders:

    def test_missing_or_invalid_user_context_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity in
        which they act. If either header is missing or empty, or if the role value
        is not one of the declared roles, the request is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_returns_400
        """
        payload = {"name": "NoAuth", "location": "Seattle",
                   "annual_hours_worked": 10000}

        # No auth headers at all.
        resp_missing = api.create_project(payload, headers={})
        validate_error(resp_missing,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

        # A role value outside the declared set.
        resp_bad_role = api.create_project(
            payload, headers={"X-User-ID": "x-1", "X-User-Role": "Foreman",
                              "Content-Type": "application/json"},
        )
        validate_error(resp_bad_role,
                       ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRoleEnforcement:

    def test_subcontractor_rep_cannot_create_permits(self, api):
        """PRD §2.1: "A request whose role is not authorized for the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.9: "Second (priority 2): the role must be authorized for the
        endpoint, including the `SubcontractorRep` ownership comparison of §2.1."

        Design: Corner/rbac/subcontractor_rep_cannot_create_permits
        """
        project = create_project(name="North Beach", annual_hours_worked=5000)
        sub = create_subcontractor(project["id"], company_name="Amp",
                                   trade="electrical")
        # Role check (priority 2) fires before any shape/existence processing,
        # so even an empty body is denied.
        resp = api.create_permit({}, make_subcontractor_rep_headers(sub["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_site_superintendent_cannot_issue_permit(self, api):
        """PRD §2.9: "Second (priority 2): the role must be authorized for the
        endpoint, including the `SubcontractorRep` ownership comparison of §2.1.
        Third (priority 3): every identifier in the path must exist"
        PRD §4: POST /safety/permits/{permitId}/issue — "SafetyManager".

        Design: Corner/rbac/site_superintendent_cannot_issue_permit
        """
        create_project(name="North Beach 2", annual_hours_worked=5000)
        # Issuance is SafetyManager-exclusive: the role denial at priority 2
        # fires before the not-found check at priority 3.
        resp = api.issue_permit(NON_EXISTENT_UUID, {}, SS)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_compliance_auditor_read_only_enforced(self, api):
        """PRD §2.1: "The `ComplianceAuditor` is a read-only regulatory auditor
        with full read access — including drug test records and the OSHA
        summary — and no write operations."
        PRD §3.6: "The response exposes `year`, `hours_worked`,
        `recordable_count_final`, `recordable_count_provisional`,
        `dart_count_final`, `dart_count_provisional`, `trir_final`,
        `trir_provisional`, `dart_rate_final`, `dart_rate_provisional`, and
        `rate_spread_final`."

        Design: Corner/rbac/compliance_auditor_read_only_enforced
        """
        set_clock("2026-08-01T08:00:00Z")
        project = create_project(name="Audit Site", annual_hours_worked=200000)

        # Writes are denied.
        resp_write = api.create_project(
            {"name": "Denied", "location": "X", "annual_hours_worked": 1}, AUDITOR
        )
        validate_error(resp_write, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        # Auditor-only reads are allowed.
        resp_list = api.list_drug_tests(AUDITOR)
        data, _meta = validate_paginated(resp_list)
        assert data == []

        resp_summary = api.get_osha_summary(project["id"], AUDITOR,
                                            params={"year": 2026})
        summary = validate_success(resp_summary, 200)
        assert summary["recordable_count_final"] == 0
        assert summary["trir_final"] == 0.0


class TestNotFoundCatalog:

    def test_missing_worker_and_permit_return_typed_404(self, api):
        """PRD §2.10: "the first identifier that does not resolve yields that
        resource's not-found error: `ERR_PROJECT_NOT_FOUND`,
        `ERR_SAFETY_PLAN_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`,
        `ERR_CERTIFICATE_NOT_FOUND`, `ERR_SUBCONTRACTOR_NOT_FOUND`,
        `ERR_HUDDLE_NOT_FOUND`, `ERR_JHA_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`,
        `ERR_DEFICIENCY_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`,
        `ERR_PERMIT_NOT_FOUND`, or `ERR_DRUG_TEST_NOT_FOUND`, each with HTTP 404."

        Design: Corner/errors/get_missing_worker_and_permit_return_not_found
        """
        create_project(name="Existing", annual_hours_worked=10000)
        resp_worker = api.get_worker(NON_EXISTENT_UUID, SM)
        validate_error(resp_worker, ApiErrorId.ERR_WORKER_NOT_FOUND)
        resp_permit = api.get_permit(NON_EXISTENT_UUID, SM)
        validate_error(resp_permit, ApiErrorId.ERR_PERMIT_NOT_FOUND)


class TestListEndpoints:

    def test_pagination_defaults_and_total_count(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips that many items from the front of the result set and
        defaults to 0. Unless otherwise specified, every list endpoint returns
        resources sorted by `created_at` in ascending order."
        PRD §2.3: "Paginated list responses include `limit`, `offset`,
        `total_count`, and `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_pagination_defaults_and_total_count
        """
        # Distinct logical-clock instants make the created_at order unambiguous.
        set_clock("2026-08-01T08:00:00Z")
        p1 = create_project(name="Alpha", annual_hours_worked=10000)
        set_clock("2026-08-01T08:01:00Z")
        p2 = create_project(name="Beta", location="Kent", annual_hours_worked=20000)

        resp1 = api.list_projects(AUDITOR, params={"limit": 1, "offset": 0})
        data1, meta1 = validate_paginated(resp1)
        assert len(data1) == 1
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        assert data1[0]["id"] == p1["id"]

        resp2 = api.list_projects(AUDITOR, params={"limit": 1, "offset": 1})
        data2, meta2 = validate_paginated(resp2)
        assert len(data2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert data2[0]["id"] == p2["id"]

        body = resp2.json()
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["response_type"] == "array"

    def test_worker_filter_by_project_and_status(self, api):
        """PRD §3.2: "Workers can be listed with optional `project_id`,
        `subcontractor_id`, and `status` filters, or fetched individually."

        Design: Corner/endpoints/worker_filter_by_project_and_status
        """
        set_clock("2026-08-01T08:00:00Z")
        p1 = create_project(name="Site A", annual_hours_worked=10000)
        p2 = create_project(name="Site B", location="Kent", annual_hours_worked=10000)
        plan = create_plan(p1["id"], effective_date="2026-08-01")
        activate_plan(plan["id"], p1["version"])
        w1 = create_worker(p1["id"], full_name="D Esh")
        w2 = create_worker(p2["id"], full_name="E Fry")
        complete_orientation(w1["id"])  # p1 has an ACTIVE plan; w1 -> ORIENTED

        data_p1, meta_p1 = validate_paginated(
            api.list_workers(SM, params={"project_id": p1["id"]})
        )
        assert meta_p1["total_count"] == 1
        assert data_p1[0]["id"] == w1["id"]

        _d, meta_oriented = validate_paginated(
            api.list_workers(SM, params={"project_id": p1["id"],
                                         "status": "ORIENTED"})
        )
        assert meta_oriented["total_count"] == 1

        data_cleared, meta_cleared = validate_paginated(
            api.list_workers(SM, params={"project_id": p1["id"],
                                         "status": "CLEARED"})
        )
        assert meta_cleared["total_count"] == 0
        assert data_cleared == []
