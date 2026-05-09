"""Authentication, RBAC, pagination, and not-found / existence tests.

PRD §2.1 (header presence + RBAC), §2.3 (pagination), §2.6 (path-id resolution).
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_draft_project,
    create_project_payload,
    future_dates,
    make_principal_investigator_headers,
    setup_active_project_with_budget,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestMissingUserContext:
    """PRD §2.1: 'If either header is missing or empty, the request is rejected with
    ERR_MISSING_USER_CONTEXT (HTTP 400).'"""

    def test_missing_both_headers(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is rejected
        with ERR_MISSING_USER_CONTEXT (HTTP 400)."

        Claim: a request with no auth headers returns ERR_MISSING_USER_CONTEXT.
        """
        resp = api.list_projects(headers={}, params={"limit": 10})
        validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)

    def test_missing_user_id(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is rejected
        with ERR_MISSING_USER_CONTEXT (HTTP 400)."

        Claim: missing X-User-ID alone returns ERR_MISSING_USER_CONTEXT.
        """
        resp = api.list_projects(headers={"X-User-Role": "ResearchAdmin"})
        validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)

    def test_missing_role(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is rejected
        with ERR_MISSING_USER_CONTEXT (HTTP 400)."

        Claim: missing X-User-Role alone returns ERR_MISSING_USER_CONTEXT.
        """
        resp = api.list_projects(headers={"X-User-ID": "some-user"})
        validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)

    def test_empty_user_id(self, api):
        """PRD §2.1: "If either header is missing or empty, the request is rejected
        with ERR_MISSING_USER_CONTEXT (HTTP 400)."

        Claim: empty X-User-ID returns ERR_MISSING_USER_CONTEXT.
        """
        resp = api.list_projects(headers={"X-User-ID": "", "X-User-Role": "ResearchAdmin"})
        validate_error(resp, ApiErrorId.ERR_MISSING_USER_CONTEXT.value)


class TestInsufficientPermissions:
    """PRD §2.1: 'If the role is well-formed but lacks permission for the requested
    operation under the role-based access control matrix, the request is rejected with
    ERR_INSUFFICIENT_PERMISSIONS (HTTP 403).'"""

    def test_peer_reviewer_cannot_create_project(self, api, peer_reviewer_headers):
        """PRD §4 endpoint table: 'POST /projects | Create a project draft | PrincipalInvestigator'.

        PRD §2.1: "If the role is well-formed but lacks permission for the requested
        operation under the role-based access control matrix, the request is rejected
        with ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

        Claim: PeerReviewer cannot create a project — ERR_INSUFFICIENT_PERMISSIONS.
        """
        start, end = future_dates(api)
        payload = create_project_payload(
            principal_investigator_id="some-pi",
            planned_start_date=start,
            planned_end_date=end,
        )
        resp = api.create_project(payload, peer_reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_pi_cannot_approve_project(self, api):
        """PRD §4 endpoint table: 'POST /projects/{projectId}/approve | ... | ResearchAdmin'.

        PRD §2.1: "If the role is well-formed but lacks permission for the requested
        operation under the role-based access control matrix, the request is rejected
        with ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

        Claim: a PrincipalInvestigator cannot approve a project — ERR_INSUFFICIENT_PERMISSIONS.
        """
        project = create_draft_project(api, pi_id="pi-abc")
        headers = make_principal_investigator_headers("pi-abc")
        resp = api.approve_project(project["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_dept_approver_cannot_finance_approve_reimbursement(self, api, dept_headers):
        """PRD §4 endpoint table: 'POST /reimbursements/{reimbursementId}/finance-approve | ... | FinanceOfficer'.

        PRD §2.1: "If the role is well-formed but lacks permission for the requested
        operation under the role-based access control matrix, the request is rejected
        with ERR_INSUFFICIENT_PERMISSIONS (HTTP 403)."

        Claim: DepartmentApprover cannot invoke finance-approve — ERR_INSUFFICIENT_PERMISSIONS.
        """
        # We just need a 404-able id so the request resolves to RBAC, not a real resource.
        resp = api.finance_approve_reimbursement(NON_EXISTENT_UUID, dept_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


class TestPathIdNotFound:
    """PRD §2.6: '... the request is rejected with the appropriate not-found error
    for that resource — ERR_PROJECT_NOT_FOUND, ERR_BUDGET_ITEM_NOT_FOUND, ...
    all returning HTTP 404. Resolution stops at the first segment that fails.'"""

    def test_get_project_not_found(self, api, research_admin_headers):
        """PRD §2.6: "If any segment fails to resolve to an existing row, the request
        is rejected with the appropriate not-found error for that resource —
        ERR_PROJECT_NOT_FOUND, ERR_BUDGET_ITEM_NOT_FOUND, ERR_BUDGET_ADJUSTMENT_NOT_FOUND,
        ERR_REIMBURSEMENT_NOT_FOUND, ERR_CLOSING_AUDIT_NOT_FOUND, ERR_COMPLIANCE_RULE_NOT_FOUND,
        ERR_ALLOCATION_RUN_NOT_FOUND, or ERR_PEER_REVIEW_NOT_FOUND — all returning HTTP 404."

        Claim: GET /projects/{nonexistent} returns ERR_PROJECT_NOT_FOUND.
        """
        resp = api.get_project(NON_EXISTENT_UUID, research_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND.value)

    def test_get_budget_item_not_found(self, api, research_admin_headers):
        """PRD §2.6: "If any segment fails to resolve to an existing row, the request
        is rejected with the appropriate not-found error for that resource —
        ERR_PROJECT_NOT_FOUND, ERR_BUDGET_ITEM_NOT_FOUND, ERR_BUDGET_ADJUSTMENT_NOT_FOUND,
        ERR_REIMBURSEMENT_NOT_FOUND, ERR_CLOSING_AUDIT_NOT_FOUND, ERR_COMPLIANCE_RULE_NOT_FOUND,
        ERR_ALLOCATION_RUN_NOT_FOUND, or ERR_PEER_REVIEW_NOT_FOUND — all returning HTTP 404."

        Claim: GET /budget-items/{nonexistent} returns ERR_BUDGET_ITEM_NOT_FOUND.
        """
        resp = api.get_budget_item(NON_EXISTENT_UUID, research_admin_headers)
        validate_error(resp, ApiErrorId.ERR_BUDGET_ITEM_NOT_FOUND.value)

    def test_get_budget_adjustment_not_found(self, api, research_admin_headers):
        """PRD §2.6: "If any segment fails to resolve to an existing row, the request
        is rejected with the appropriate not-found error for that resource —
        ERR_PROJECT_NOT_FOUND, ERR_BUDGET_ITEM_NOT_FOUND, ERR_BUDGET_ADJUSTMENT_NOT_FOUND,
        ERR_REIMBURSEMENT_NOT_FOUND, ERR_CLOSING_AUDIT_NOT_FOUND, ERR_COMPLIANCE_RULE_NOT_FOUND,
        ERR_ALLOCATION_RUN_NOT_FOUND, or ERR_PEER_REVIEW_NOT_FOUND — all returning HTTP 404."

        Claim: GET /budget-adjustments/{nonexistent} returns ERR_BUDGET_ADJUSTMENT_NOT_FOUND.
        """
        resp = api.get_budget_adjustment(NON_EXISTENT_UUID, research_admin_headers)
        validate_error(resp, ApiErrorId.ERR_BUDGET_ADJUSTMENT_NOT_FOUND.value)

    def test_get_reimbursement_not_found(self, api, research_admin_headers):
        """PRD §2.6: "If any segment fails to resolve to an existing row, the request
        is rejected with the appropriate not-found error for that resource —
        ERR_PROJECT_NOT_FOUND, ERR_BUDGET_ITEM_NOT_FOUND, ERR_BUDGET_ADJUSTMENT_NOT_FOUND,
        ERR_REIMBURSEMENT_NOT_FOUND, ERR_CLOSING_AUDIT_NOT_FOUND, ERR_COMPLIANCE_RULE_NOT_FOUND,
        ERR_ALLOCATION_RUN_NOT_FOUND, or ERR_PEER_REVIEW_NOT_FOUND — all returning HTTP 404."

        Claim: GET /reimbursements/{nonexistent} returns ERR_REIMBURSEMENT_NOT_FOUND.
        """
        resp = api.get_reimbursement(NON_EXISTENT_UUID, research_admin_headers)
        validate_error(resp, ApiErrorId.ERR_REIMBURSEMENT_NOT_FOUND.value)

    def test_get_closing_audit_not_found(self, api, research_admin_headers):
        """PRD §2.6: "If any segment fails to resolve to an existing row, the request
        is rejected with the appropriate not-found error for that resource —
        ERR_PROJECT_NOT_FOUND, ERR_BUDGET_ITEM_NOT_FOUND, ERR_BUDGET_ADJUSTMENT_NOT_FOUND,
        ERR_REIMBURSEMENT_NOT_FOUND, ERR_CLOSING_AUDIT_NOT_FOUND, ERR_COMPLIANCE_RULE_NOT_FOUND,
        ERR_ALLOCATION_RUN_NOT_FOUND, or ERR_PEER_REVIEW_NOT_FOUND — all returning HTTP 404."

        Claim: GET /closing-audits/{nonexistent} returns ERR_CLOSING_AUDIT_NOT_FOUND.
        """
        resp = api.get_closing_audit(NON_EXISTENT_UUID, research_admin_headers)
        validate_error(resp, ApiErrorId.ERR_CLOSING_AUDIT_NOT_FOUND.value)

    def test_get_allocation_run_not_found(self, api, research_admin_headers):
        """PRD §2.6: "If any segment fails to resolve to an existing row, the request
        is rejected with the appropriate not-found error for that resource —
        ERR_PROJECT_NOT_FOUND, ERR_BUDGET_ITEM_NOT_FOUND, ERR_BUDGET_ADJUSTMENT_NOT_FOUND,
        ERR_REIMBURSEMENT_NOT_FOUND, ERR_CLOSING_AUDIT_NOT_FOUND, ERR_COMPLIANCE_RULE_NOT_FOUND,
        ERR_ALLOCATION_RUN_NOT_FOUND, or ERR_PEER_REVIEW_NOT_FOUND — all returning HTTP 404."

        Claim: GET /allocation-runs/{nonexistent} returns ERR_ALLOCATION_RUN_NOT_FOUND.
        """
        resp = api.get_allocation_run(NON_EXISTENT_UUID, research_admin_headers)
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_RUN_NOT_FOUND.value)


class TestPagination:
    """PRD §2.3: 'A limit outside the inclusive range from 1 to 100, or an offset
    strictly less than 0, is rejected with ERR_INVALID_PAGINATION_PARAMETERS (HTTP 400).'"""

    @pytest.mark.parametrize("limit", [0, -1, 101, 1000])
    def test_invalid_limit(self, api, research_admin_headers, limit):
        """PRD §2.3: "A limit outside the inclusive range from 1 to 100, or an offset
        strictly less than 0, is rejected with ERR_INVALID_PAGINATION_PARAMETERS (HTTP 400)."

        Claim: limit outside [1, 100] returns ERR_INVALID_PAGINATION_PARAMETERS.
        """
        resp = api.list_projects(research_admin_headers, params={"limit": limit, "offset": 0})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS.value)

    def test_invalid_offset_negative(self, api, research_admin_headers):
        """PRD §2.3: "A limit outside the inclusive range from 1 to 100, or an offset
        strictly less than 0, is rejected with ERR_INVALID_PAGINATION_PARAMETERS (HTTP 400)."

        Claim: negative offset returns ERR_INVALID_PAGINATION_PARAMETERS.
        """
        resp = api.list_projects(research_admin_headers, params={"limit": 10, "offset": -1})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION_PARAMETERS.value)

    def test_valid_pagination(self, api, research_admin_headers):
        """PRD §2.3: "Each list response carries limit, offset, total_count, and has_more
        in the meta object: total_count is the total number of records matching the filter,
        and has_more is true exactly when more records exist beyond the current page."

        Claim: a valid list response includes meta.total_count and meta.has_more.
        """
        # Ensure at least one project exists for non-empty list.
        setup_active_project_with_budget(api, pi_id="pi-list-check")
        resp = api.list_projects(research_admin_headers, params={"limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert "total_count" in meta
        assert "has_more" in meta
        assert meta["limit"] == 1
        assert meta["offset"] == 0
