"""Identity headers, validation ordering, and role authorization (PRD §2.1, §2.10, §4)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    create_active_project,
    create_owner_report,
    create_project,
    current_project_version,
    make_project_engineer_headers,
    make_reviewer_headers,
    price_assessment,
    setup_estimated_assessment,
    validate_error,
)
from test_helpers import TEST_USERS

PA = TEST_USERS["platform_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
PE = TEST_USERS["project_engineer_headers"]
OR = TEST_USERS["owner_rep_headers"]


class TestAuthAndOrdering:
    def test_request_missing_auth_headers_returns_400(self, api):
        """PRD §2.1: "A request with either header missing or blank, or whose role value
        is not one of the declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/request_missing_auth_headers_returns_400
        """
        resp = api.list_projects({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)

    def test_existence_checked_before_body_shape(self, api):
        """PRD §2.10: "This ordering has observable consequences: an unknown resource id
        surfaces as a 404 before any state or business rule runs, a stale version
        surfaces before the posture gate, and a pricing request on an assessment in the
        wrong state fails with its state error before the contingency balance is ever
        consulted."
        A create against a nonexistent project that also omits required body fields
        returns the 404, not the 400 shape error.

        Design: Corner/validations/existence_checked_before_body_shape
        """
        real = create_project("Real")
        resp = api.create_rfi(
            NON_EXISTENT_UUID,
            {"expected_project_version": real["version"]},
            PE,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_FOUND, 404)


class TestRoleDenials:
    def test_reviewer_role_cannot_create_rfi_forbidden(self, api):
        """PRD §2.1: "A request whose role is valid but not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/v1/projects/{projectId}/rfis` | Create an RFI (OCC on the
        project) | ProjectEngineer, SubcontractorRep |" — Reviewer is not listed.

        Design: Corner/rbac/reviewer_role_cannot_create_rfi_forbidden
        """
        project = create_active_project("P")
        resp = api.create_rfi(
            project["id"],
            {
                "subject": "S",
                "question_text": "Q",
                "expected_project_version": current_project_version(project["id"]),
            },
            make_reviewer_headers("reviewer-who-is-not-a-pe"),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_ownerrep_cannot_publish_report_forbidden(self, api):
        """PRD §2.1: "A request whose role is valid but not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/v1/owner-reports/{reportId}/publish` | Publish a draft
        report, freezing its metrics | ProjectEngineer |" — OwnerRep is not listed.

        Design: Corner/rbac/ownerrep_cannot_publish_report_forbidden
        """
        project = create_active_project("P")
        report = create_owner_report(project["id"], "2026-08-01", "2026-08-31")

        resp = api.publish_owner_report(report["id"], OR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_platformadmin_cannot_drive_project_lifecycle_forbidden(self, api):
        """PRD §2.1: "A request whose role is valid but not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/v1/projects/{projectId}/activate` | Activate a project
        (`SETUP` → `ACTIVE`) | ProjectManager |" — PlatformAdmin is not listed.

        Design: Corner/rbac/platformadmin_cannot_drive_project_lifecycle_forbidden
        """
        project = create_project("P")
        resp = api.activate_project(project["id"], PA)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_project_engineer_cannot_accept_impact_forbidden(self, api):
        """PRD §2.1: "A request whose role is valid but not authorized for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "| POST | `/v1/impact-assessments/{assessmentId}/accept` | Accept a
        priced assessment | ProjectManager |" — ProjectEngineer is not listed.
        PRD §2.10: "Second, the caller's role is checked against the endpoint's
        authorized roles (`ERR_FORBIDDEN_ROLE`)." — the role check precedes the
        segregation-of-duties check (ninth), so the engineer who priced is stopped at
        the role gate.

        Design: Corner/rbac/project_engineer_cannot_accept_impact_forbidden
        """
        ctx = setup_estimated_assessment()
        price_assessment(ctx["assessment"]["id"], 100_000)

        resp = api.accept_impact_assessment(
            ctx["assessment"]["id"], make_project_engineer_headers("op-pe-2")
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
