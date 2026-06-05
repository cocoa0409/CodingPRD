"""Error, RBAC, and optimistic-concurrency corner tests (Corner queue: errors,
roles, cross_cutting_complexity_layers sections)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    OWNER, CONTRACTOR, ARCHITECT,
    JAN,
    build_user_headers,
    create_project, create_sov_line,
    setup_project_with_one_sov_line, setup_project_with_two_sov_lines,
    create_change_order, submit_change_order, get_project_version,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Errors
# ===========================================================================
class TestReleaseExceedsHeld:
    def test_release_one_cent_over_held_rejected(self, api):
        """PRD §3.8: "the requested `amount_cents` is at most the project's current
        `retainage_held_cents` (else `ERR_RELEASE_EXCEEDS_HELD`, HTTP 422)".

        Design: Corner/errors/release_exceeds_held_triggered
        """
        project, sov1, sov2, pay_app, release = fx.setup_release_requested(45_001)
        pv_cur = get_project_version(project["id"])
        resp = api.approve_retention_release(
            release["id"], {"expected_project_version": pv_cur}, OWNER
        )
        validate_error(resp, ApiErrorId.ERR_RELEASE_EXCEEDS_HELD.value, 422)
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        assert proj["retainage_held_cents"] == 45000  # unchanged after rejection.


# ===========================================================================
# RBAC
# ===========================================================================
class TestContractorCannotApproveChangeOrder:
    def test_contractor_approve_denied(self, api):
        """PRD §2.1: "When the headers are valid but the role is not permitted to invoke the
        requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/roles/contractor_cannot_approve_change_order
        """
        project, sov1, sov2, co = fx.setup_submitted_change_order(
            change_order_amount_cents=50_000,
            line_edits=[{"action": "ADD", "item_no": "003", "description": "X",
                         "scheduled_value_delta_cents": 50_000}],
        )
        pv_cur = get_project_version(project["id"])
        resp = api.approve_change_order(
            co["id"], {"expected_project_version": pv_cur}, CONTRACTOR
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


class TestMissingAuthHeaders:
    def test_unknown_role_returns_unauthenticated(self, api):
        """PRD §2.1: "If either header is absent, or if X-User-Role is not one of these three
        known roles, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/roles/missing_auth_headers_returns_unauthenticated
        """
        ghost = build_user_headers("nobody", "Ghost")
        resp = api.create_project(
            {"name": "NoAuth", "owner_user_id": "x", "original_contract_sum_cents": 100_000},
            ghost,
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


class TestArchitectCannotCreateSovLine:
    def test_architect_create_sov_line_denied(self, api):
        """PRD §2.1: "When the headers are valid but the role is not permitted to invoke the
        requested operation, the request is rejected with ERR_FORBIDDEN_ROLE (HTTP 403)."

        Design: Corner/roles/architect_cannot_create_sov_line
        """
        project = create_project(1_000_000, name="ArchP")
        resp = api.create_sov_line(
            {"project_id": project["id"], "item_no": "001", "description": "Foundation",
             "scheduled_value_cents": 600_000},
            ARCHITECT,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


# ===========================================================================
# Optimistic concurrency control
# ===========================================================================
class TestOccStaleProjectVersionOnPayAppCreate:
    def test_pay_app_create_with_stale_version_rejected(self, api):
        """PRD §2.6: "If that value does not equal the project's current version — because a
        change-order approval, a prior certification, or a retention-release approval has
        advanced the project since the client read it — the create is rejected with
        ERR_STALE_PROJECT_VERSION (HTTP 412)".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_pay_app_create
        """
        project, sov1, sov2 = setup_project_with_two_sov_lines()
        pv_stale = project["version"]
        co = create_change_order(
            project["id"], "CO-1", 50_000,
            [{"action": "ADD", "item_no": "003", "description": "X",
              "scheduled_value_delta_cents": 50_000}],
        )
        submit_change_order(co["id"])
        # Approve with the still-current version, bumping project to version 2.
        validate_success(
            api.approve_change_order(
                co["id"], {"expected_project_version": pv_stale}, OWNER
            ),
            200,
        )
        resp = api.create_pay_application(
            {"project_id": project["id"], "application_number": 1,
             "period_from": JAN[0], "period_to": JAN[1],
             "expected_project_version": pv_stale},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)


class TestOccStaleProjectVersionOnRetentionReleaseCreate:
    def test_retention_release_create_with_stale_version_rejected(self, api):
        """PRD §2.6: "Creating a retention release likewise requires an
        expected_project_version field carrying the client's last observed Project.version;
        if a certification or another approved release has since changed the held retainage
        and bumped the project's version, the create is rejected with the same
        ERR_STALE_PROJECT_VERSION (HTTP 412)".

        Design: Corner/cross_cutting_complexity_layers/occ_stale_project_version_on_retention_release_create
        """
        project, sov1 = setup_project_with_one_sov_line()
        pv_stale = project["version"]
        app = fx.create_pay_application(project["id"], 1, JAN, pv_stale)
        fx.add_pay_app_line(app["id"], sov1["id"], 100_000, 0)
        fx.submit_pay_application(app["id"])
        fx.certify_pay_application(app["id"])  # bumps version 1 -> 2.
        resp = api.create_retention_release(
            {"project_id": project["id"], "amount_cents": 5_000,
             "expected_project_version": pv_stale},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION.value, 412)


class TestOccCorrectVersionPayAppCreateSucceeds:
    def test_pay_app_create_with_fresh_version_succeeds(self, api):
        """PRD §2.6: "Creating a pay application requires an expected_project_version field in
        the request body carrying the Project.version the client last observed."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_pay_app_create_succeeds
        """
        project, sov1 = setup_project_with_one_sov_line(name="OccOk")
        pv_cur = get_project_version(project["id"])
        resp = api.create_pay_application(
            {"project_id": project["id"], "application_number": 1,
             "period_from": JAN[0], "period_to": JAN[1],
             "expected_project_version": pv_cur},
            CONTRACTOR,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"
