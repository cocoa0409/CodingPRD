"""Identity-header, role-permission, and segregation-of-duties claims
(PRD §2.1, §2.8, §3.6, §4)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, create_registry_payload,
    setup_panel_scenario, submit_evidence, create_campaign, schedule_campaign,
    make_admin_headers, make_panel_manager_headers,
    make_quality_reviewer_headers, make_reconciliation_bot_headers,
)


class TestIdentityHeaders:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying
        the acting operator, and `X-User-Role`, identifying the role under which
        that operator acts. A request missing either header, or carrying a malformed
        value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        resp = api.list_registries({})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRolePermissions:
    def test_insufficient_permissions_role_not_allowed(self, api):
        """PRD §2.1: "A request whose role is not permitted to invoke the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4 endpoint table: "POST | /population-health/registries | Create a
        population registry | ProgramAdministrator".

        Design: Corner/validations/insufficient_permissions_role_not_allowed
        """
        resp = api.create_registry(create_registry_payload(name="R"),
                                   make_panel_manager_headers("pm_9"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_panel_manager_cannot_approve_evidence(self, api):
        """PRD §3.6: "Approval is exclusive to `QualityReviewer`".
        PRD §2.1: "A request whose role is not permitted to invoke the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/panel_manager_cannot_approve_evidence
        """
        scenario = setup_panel_scenario(num_members=1)
        evidence = submit_evidence(scenario["gaps"][0]["id"], submitter_id="pm_1")
        resp = api.approve_evidence(evidence["id"], {},
                                    make_panel_manager_headers("pm_2"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_quality_reviewer_cannot_launch_campaign(self, api):
        """PRD §3.4: "Launching — performed manually by an administrator, or
        automatically by the system when the clock reaches `starts_at`".
        PRD §2.1: "A request whose role is not permitted to invoke the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4 endpoint table: "POST | /population-health/outreach-campaigns/{id}/launch
        | Launch a campaign | ProgramAdministrator".

        Design: Corner/rbac/quality_reviewer_cannot_launch_campaign
        """
        scenario = setup_panel_scenario(num_members=1)
        campaign = create_campaign(scenario["registry"]["id"], scenario["panel"]["id"],
                                   scenario["measure"]["id"])
        schedule_campaign(campaign["id"])
        resp = api.launch_campaign(campaign["id"], make_quality_reviewer_headers("qr_1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_data_reconciliation_bot_cannot_approve_evidence(self, api):
        """PRD §3.6: "Approval is exclusive to `QualityReviewer`".
        PRD §2.1: "`DataReconciliationBot` — the system actor that processes the
        claims feed and reopens mismatched gaps."
        PRD §2.1: "A request whose role is not permitted to invoke the target
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/data_reconciliation_bot_cannot_approve_evidence
        """
        scenario = setup_panel_scenario(num_members=1)
        evidence = submit_evidence(scenario["gaps"][0]["id"], submitter_id="pm_1")
        resp = api.approve_evidence(evidence["id"], {},
                                    make_reconciliation_bot_headers("bot_1"))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
