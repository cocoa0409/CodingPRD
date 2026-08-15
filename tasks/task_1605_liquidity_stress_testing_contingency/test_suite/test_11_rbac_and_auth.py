"""Role-based access control and authentication.

Corner instances: missing_auth_headers_unauthenticated,
analyst_cannot_approve_playbook, riskofficer_cannot_activate_playbook,
riskofficer_cannot_deescalate_posture,
platform_admin_cannot_read_business_resource.
"""
from test_helpers import (
    ApiErrorId,
    USER_ANALYST_1,
    USER_ANALYST_9,
    USER_OFFICER_2,
    create_liquid_asset_payload,
    make_analyst_headers,
    make_approved_playbook,
    make_committee_headers,
    make_metric,
    make_officer_headers,
    make_scenario,
    make_tested_playbook,
    post_reading,
    setup_line_with_pledge,
    validate_error,
    validate_success,
)

COMMITTEE = make_committee_headers("lc_1")


def _drawdown_action(line_id, proceeds):
    return {
        "kind": "LINE_DRAWDOWN", "sequence_no": 1,
        "estimated_proceeds_cents": proceeds, "settlement_lag_days": 0,
        "line_id": line_id,
    }


def _approved_playbook(api):
    scenario = make_scenario(name="Base", tier="BASELINE")
    line, _asset, _pledge = setup_line_with_pledge()
    playbook, _actions = make_approved_playbook(
        scenario["id"], [_drawdown_action(line["id"], 60_000_000)],
        target_capacity_cents=60_000_000,
        creator=USER_ANALYST_1, approver=USER_OFFICER_2,
    )
    return playbook


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two identity headers:
        `X-User-ID` and `X-User-Role`. A request missing either header, or
        presenting a role outside the declared set, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.9: "Validation runs in a fixed order so that a request failing
        several checks always surfaces the earliest failure. First,
        authentication of the two identity headers (`ERR_UNAUTHENTICATED`)."

        Design: Corner/validations/missing_auth_headers_unauthenticated
        """
        resp = api.create_liquid_asset(
            create_liquid_asset_payload(
                asset_class="LEVEL_1", reference="A", market_value_cents=1000,
            ),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


class TestRbacDenials:
    def test_analyst_cannot_approve_playbook(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        for the operation — including the state-specific role rules called out
        in §3, such as escalated-breach remediation and posture de-escalation
        being reserved for the committee — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §3.9: "Approval is a `RiskOfficer` act guarded by segregation of
        duties".

        Design: Corner/rbac/analyst_cannot_approve_playbook
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        line, _asset, _pledge = setup_line_with_pledge()
        tested, _actions = make_tested_playbook(
            scenario["id"], [_drawdown_action(line["id"], 60_000_000)],
            target_capacity_cents=60_000_000, creator=USER_ANALYST_1,
        )
        # TreasuryAnalyst is not in the approve endpoint's role set.
        resp = api.approve_playbook(tested["id"], make_analyst_headers(USER_ANALYST_9))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_riskofficer_cannot_activate_playbook(self, api):
        """PRD §3.9: "Activation belongs to the `LiquidityCommittee` and is
        doubly gated."
        PRD §2.1: "A request whose role is authenticated but not permitted for
        the operation — including the state-specific role rules called out in
        §3, such as escalated-breach remediation and posture de-escalation
        being reserved for the committee — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/riskofficer_cannot_activate_playbook
        """
        playbook = _approved_playbook(api)
        resp = api.activate_playbook(playbook["id"], make_officer_headers("ro_1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_riskofficer_cannot_deescalate_posture(self, api):
        """PRD §3.6: "De-escalation below the current level is committee-only,
        so any other role attempting it is rejected with `ERR_FORBIDDEN`".

        Design: Corner/rbac/riskofficer_cannot_deescalate_posture
        """
        metric = make_metric(code="M", name="m")
        post_reading(metric["id"], 6000)  # RED -> posture auto-escalates to SEVERE
        # Corrective reading: band back to GREEN (red_count 0, no open
        # breaches), so raw_level NORMAL is below the current SEVERE.
        post_reading(metric["id"], 500, observed_at="2026-08-02T00:00:00Z")
        resp = api.run_posture_evaluation(make_officer_headers("ro_1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_platform_admin_cannot_read_business_resource(self, api, admin_headers):
        """PRD §2.1: "`PlatformAdmin` — the test-driving operator for the
        logical clock."
        PRD §2.1: "A request whose role is authenticated but not permitted for
        the operation — including the state-specific role rules called out in
        §3, such as escalated-breach remediation and posture de-escalation
        being reserved for the committee — is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/platform_admin_cannot_read_business_resource
        """
        scenario = make_scenario(name="Base", tier="BASELINE")
        resp = api.get_scenario(scenario["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
