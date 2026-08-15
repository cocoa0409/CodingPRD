"""RBAC denials, counterparty ownership, pagination envelope, error envelope, 404s."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_active_project,
    create_project,
    create_submittal,
    create_report_issued_visit,
    create_payment_application,
    create_change_order,
    recommend_change_order,
    set_clock,
    make_firm_admin_headers,
    make_architect_headers,
    make_contractor_headers,
    make_owner_headers,
    build_user_headers,
)

SOV_A_ONLY = [{"line_code": "A", "description": "Concrete",
               "scheduled_value_cents": 10000000}]


class TestRbacExclusiveDenials:
    def test_contractor_cannot_review_submittal(self, api):
        """PRD 2.1: "A request whose role is not among the roles authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); the
        per-endpoint role assignments are enumerated in Section 4." Section 4:
        `POST /ca/submittals/{id}/review` is authorized for ArchitectCA only.

        Design: Corner/rbac/contractor_cannot_review_submittal
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        submittal = create_submittal(project["id"])
        resp = api.review_submittal(
            submittal["id"], {"outcome": "APPROVED"},
            make_contractor_headers(project["contractor_user_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        current = get_success_data(api.get_submittal(submittal["id"], make_architect_headers()))
        assert current["status"] == "UNDER_REVIEW"

    def test_architect_cannot_create_submittal(self, api):
        """PRD 2.1: "A request whose role is not among the roles authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".
        Section 4: `POST /ca/submittals` is authorized for Contractor only.

        Design: Corner/rbac/architect_cannot_create_submittal
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        resp = api.create_submittal(
            {"project_id": project["id"], "spec_section": "03 30 00",
             "required_on_site_date": "2026-08-25"},
            make_architect_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_owner_cannot_certify_pay_app(self, api):
        """PRD 2.1: "A request whose role is not among the roles authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".
        Section 4: `POST /ca/payment-applications/{id}/certify` is authorized for
        ArchitectCA only.

        Design: Corner/rbac/owner_cannot_certify_pay_app
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        set_clock("2026-08-20T09:00:00Z")
        visit, _ = create_report_issued_visit(
            project["id"], visit_date="2026-08-20", purpose="PAYMENT_VERIFICATION",
        )
        application = create_payment_application(
            project["id"], visit["id"], period_ending_date="2026-08-31",
        )
        resp = api.certify_payment_application(
            application["id"], make_owner_headers(project["owner_user_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        current = get_success_data(
            api.get_payment_application(application["id"], make_architect_headers()))
        assert current["status"] == "SUBMITTED"

    def test_firm_admin_cannot_decide_change_order(self, api):
        """PRD 2.1: "A request whose role is not among the roles authorized for
        the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)".
        Section 4: `POST /ca/change-orders/{id}/owner-decision` is authorized for
        Owner only.

        Design: Corner/rbac/firm_admin_cannot_decide_change_order
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        change_order = create_change_order(
            project["id"], title="Panel substitution",
            net_cost_change_cents=250000, time_extension_days=0,
        )
        recommend_change_order(change_order["id"], "ACCEPT")
        resp = api.decide_change_order(
            change_order["id"], {"decision": "ACCEPT"}, make_firm_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
        current = get_success_data(
            api.get_change_order(change_order["id"], make_firm_admin_headers()))
        assert current["status"] == "RECOMMEND_ACCEPTANCE"


class TestCounterpartyOwnership:
    def test_contractor_of_other_project_denied_counterparty(self, api):
        """PRD 2.1: "When `X-User-Role` is `Contractor`, the identifier must equal
        the acting project's `contractor_user_id` on every project-scoped write;
        when `X-User-Role` is `Owner`, it must equal the project's
        `owner_user_id`; a mismatch is rejected with
        `ERR_NOT_PROJECT_COUNTERPARTY` (HTTP 403)."

        Design: Corner/rbac/contractor_of_other_project_denied_counterparty
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        resp = api.create_submittal(
            {"project_id": project["id"], "spec_section": "03 30 00",
             "required_on_site_date": "2026-08-25"},
            make_contractor_headers("user-contractor-9"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_PROJECT_COUNTERPARTY, 403)
        listing = get_success_data(api.list_submittals(
            make_firm_admin_headers(), params={"project_id": project["id"]}))
        assert listing == []


class TestSharedReadSurface:
    def test_shared_list_endpoints_allow_all_roles(self, api):
        """PRD 4: "In the role column, "All roles" means all four roles named in
        Section 2.1." — `GET /ca/projects` ("List projects with optional
        filters") is authorized for all roles, so Owner and Contractor reads of
        the project list succeed.

        Design: Corner/rbac/shared_list_endpoints_allow_all_roles
        """
        project = create_project(sov_lines=SOV_A_ONLY)
        for headers in (
            make_owner_headers(project["owner_user_id"]),
            make_contractor_headers(project["contractor_user_id"]),
            make_firm_admin_headers(),
            make_architect_headers(),
        ):
            data, meta = validate_paginated(api.list_projects(headers))
            assert meta["total_count"] == 1


class TestMissingAuthHeaders:
    def test_get_project_missing_auth_header_returns_400(self, api):
        """PRD 2.1: "A request that omits either header, presents an empty value,
        or names a role outside these four is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/get_project_missing_auth_header_returns_400
        """
        project = create_project(sov_lines=SOV_A_ONLY)
        resp = api.get_project(project["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestPagination:
    def test_list_pagination_defaults_and_envelope(self, api):
        """PRD 2.3: "`limit` sets the maximum number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100. `offset` sets the number of items skipped and defaults to
        0. Every list endpoint returns its resources sorted by `created_at` in
        ascending order, and the `meta` object of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/list_pagination_defaults_and_envelope
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        contractor_headers = make_contractor_headers(project["contractor_user_id"])
        for question in ("Q1", "Q2", "Q3"):
            api.create_rfi(
                {"project_id": project["id"], "question": question}, contractor_headers,
            )
        owner_headers = make_owner_headers(project["owner_user_id"])
        page1, meta1 = validate_paginated(api.list_rfis(
            owner_headers, params={"project_id": project["id"], "limit": 2}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(api.list_rfis(
            owner_headers, params={"project_id": project["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        all_items, meta3 = validate_paginated(api.list_rfis(
            owner_headers, params={"project_id": project["id"]}))
        assert len(all_items) == 3
        assert meta3["limit"] == 10

    def test_list_filter_by_status(self, api):
        """PRD 3.2: "The submittal list endpoint filters by `project_id` and
        `status`."

        Design: Corner/endpoints/list_filter_by_status
        """
        project = create_active_project(sov_lines=SOV_A_ONLY)
        s1 = create_submittal(project["id"], spec_section="03 30 00")
        s2 = create_submittal(project["id"], spec_section="05 12 00",
                              required_on_site_date="2026-08-26")
        api.review_submittal(s1["id"], {"outcome": "APPROVED"}, make_architect_headers())
        approved, meta = validate_paginated(api.list_submittals(
            make_firm_admin_headers(),
            params={"project_id": project["id"], "status": "APPROVED"}))
        assert len(approved) == 1
        assert approved[0]["id"] == s1["id"]
        under_review, meta = validate_paginated(api.list_submittals(
            make_firm_admin_headers(),
            params={"project_id": project["id"], "status": "UNDER_REVIEW"}))
        assert len(under_review) == 1
        assert under_review[0]["id"] == s2["id"]


class TestNotFoundCatalog:
    def test_get_nonexistent_child_resources_return_404(self, api):
        """PRD 2.8: "Each resource type has its own not-found error, all HTTP 404:
        `ERR_PROJECT_NOT_FOUND`, `ERR_SUBMITTAL_NOT_FOUND`,
        `ERR_SITE_VISIT_NOT_FOUND`, `ERR_FIELD_REPORT_NOT_FOUND`,
        `ERR_RFI_NOT_FOUND`, `ERR_CLARIFICATION_DRAWING_NOT_FOUND`,
        `ERR_PAYMENT_APPLICATION_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`,
        `ERR_PUNCH_ITEM_NOT_FOUND`, `ERR_RECORD_DOCUMENT_NOT_FOUND`, and
        `ERR_INVOICE_NOT_FOUND`."

        Design: Corner/errors/get_nonexistent_child_resources_return_404
        """
        headers = make_architect_headers()
        validate_error(api.get_site_visit(NON_EXISTENT_UUID, headers),
                       ApiErrorId.ERR_SITE_VISIT_NOT_FOUND, 404)
        validate_error(api.get_payment_application(NON_EXISTENT_UUID, headers),
                       ApiErrorId.ERR_PAYMENT_APPLICATION_NOT_FOUND, 404)
        validate_error(api.get_change_order(NON_EXISTENT_UUID, headers),
                       ApiErrorId.ERR_CHANGE_ORDER_NOT_FOUND, 404)
        validate_error(api.get_additional_service_invoice(NON_EXISTENT_UUID, headers),
                       ApiErrorId.ERR_INVOICE_NOT_FOUND, 404)

    def test_get_nonexistent_remaining_resources_return_404(self, api):
        """PRD 2.8: "Each resource type has its own not-found error, all HTTP 404:
        `ERR_PROJECT_NOT_FOUND`, `ERR_SUBMITTAL_NOT_FOUND`,
        `ERR_SITE_VISIT_NOT_FOUND`, `ERR_FIELD_REPORT_NOT_FOUND`,
        `ERR_RFI_NOT_FOUND`, `ERR_CLARIFICATION_DRAWING_NOT_FOUND`,
        `ERR_PAYMENT_APPLICATION_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`,
        `ERR_PUNCH_ITEM_NOT_FOUND`, `ERR_RECORD_DOCUMENT_NOT_FOUND`, and
        `ERR_INVOICE_NOT_FOUND`."

        Design: Corner/errors/get_nonexistent_remaining_resources_return_404
        """
        headers = make_architect_headers()
        validate_error(api.get_field_report(NON_EXISTENT_UUID, headers),
                       ApiErrorId.ERR_FIELD_REPORT_NOT_FOUND, 404)
        validate_error(api.get_clarification_drawing(NON_EXISTENT_UUID, headers),
                       ApiErrorId.ERR_CLARIFICATION_DRAWING_NOT_FOUND, 404)
        validate_error(api.get_punch_list_item(NON_EXISTENT_UUID, headers),
                       ApiErrorId.ERR_PUNCH_ITEM_NOT_FOUND, 404)
        validate_error(api.get_record_document(NON_EXISTENT_UUID, headers),
                       ApiErrorId.ERR_RECORD_DOCUMENT_NOT_FOUND, 404)


class TestErrorEnvelopeShape:
    def test_error_envelope_shape_on_not_found(self, api):
        """PRD 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`" and "The `error_id` is a
        unique, machine-readable string that identifies the specific error. The
        `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape_on_not_found
        """
        resp = api.get_submittal(NON_EXISTENT_UUID, make_architect_headers())
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_SUBMITTAL_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestVersionDiscipline:
    def test_version_increments_on_every_mutation(self, api):
        """PRD 2.5: "`version` (integer): starts at 1 at creation and increments
        by one on every mutation, including mutations driven by cascading
        recomputation described in Section 2.11."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        project = create_project(sov_lines=SOV_A_ONLY)
        assert project["version"] == 1
        activated = validate_success(
            api.activate_project(project["id"], make_firm_admin_headers()), 200)
        assert activated["version"] == 2
        submittal = create_submittal(project["id"])
        assert submittal["version"] == 1
        reviewed = validate_success(api.review_submittal(
            submittal["id"], {"outcome": "APPROVED"}, make_architect_headers(),
        ), 200)
        assert reviewed["version"] == 2
