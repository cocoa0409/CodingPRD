"""Contractor registry lifecycle and engagement approval ladder."""
from test_helpers import (
    ApiErrorId,
    create_contractor_record,
    create_engagement_record,
    create_milestone_record,
    create_qualified_contractor,
    get_success_data,
    make_contractor_rep_headers,
    set_logical_clock,
    setup_project_in_construction,
    setup_project_in_pre_construction,
    validate_error,
    validate_success,
)


class TestContractorTerminalState:
    def test_contractor_terminal_revoked_rejects_qualify(self, api, landlord_pm_headers):
        """PRD 3.4: "Revocation ends the lifecycle: from `PENDING` it is
        unconditional, while from `QUALIFIED` it is refused so long as any
        engagement of the contractor is `ACTIVE`; `REVOKED` is terminal."
        PRD 2.7: "The targeted entity must be in a state from which the
        requested transition exists — including the parent-phase gates named
        throughout §3 — and terminal states reject every transition, else
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/contractor_terminal_revoked_rejects_qualify
        """
        contractor = create_contractor_record()
        assert contractor["qualification_status"] == "PENDING"
        contractor = get_success_data(api.revoke_contractor(contractor["id"], landlord_pm_headers))
        assert contractor["qualification_status"] == "REVOKED"

        resp = api.qualify_contractor(contractor["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_contractor(contractor["id"], landlord_pm_headers))
        assert after["qualification_status"] == "REVOKED"


class TestEngagementApprovalLadder:
    def test_engagement_approve_requires_rules_acknowledgment(self, api, landlord_pm_headers):
        """PRD 2.7: "Engagement approval checks building-rules acknowledgement
        first (`ERR_BUILDING_RULES_NOT_ACKNOWLEDGED`), then insurance currency
        (`ERR_INSURANCE_EXPIRED`), then contractor qualification
        (`ERR_CONTRACTOR_NOT_QUALIFIED`)." PRD 3.4: "The firm's own
        `ContractorRep` must first acknowledge the building rules — the
        acknowledge action sets `building_rules_acknowledged` true — after
        which the landlord's approval moves the engagement `PROPOSED` →
        `APPROVED`".

        Design: Corner/validations/engagement_approve_requires_rules_acknowledgment
        """
        sc = setup_project_in_pre_construction()
        contractor = create_qualified_contractor()
        engagement = create_engagement_record(sc["project"]["id"], contractor["id"])
        assert engagement["status"] == "PROPOSED"
        assert engagement["building_rules_acknowledged"] is False

        resp = api.approve_engagement(engagement["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_BUILDING_RULES_NOT_ACKNOWLEDGED)
        after = get_success_data(api.get_engagement(engagement["id"], landlord_pm_headers))
        assert after["status"] == "PROPOSED"

    def test_engagement_approve_with_expired_insurance_rejected(self, api, landlord_pm_headers):
        """PRD 3.4: "the landlord's approval moves the engagement `PROPOSED` →
        `APPROVED` through the three-check ladder of §2.7: acknowledgement
        (`ERR_BUILDING_RULES_NOT_ACKNOWLEDGED`), insurance currency at the
        logical clock (`ERR_INSURANCE_EXPIRED`), and the firm's `QUALIFIED`
        standing (`ERR_CONTRACTOR_NOT_QUALIFIED`)." PRD 3.4: "Qualification
        moves `PENDING` → `QUALIFIED` only while the insurance expiry is
        strictly after the current logical clock — an expired policy surfaces
        `ERR_INSURANCE_EXPIRED` (HTTP 422)."

        Design: Corner/validations/engagement_approve_with_expired_insurance_rejected
        """
        sc = setup_project_in_pre_construction()
        # Qualify while the policy is still current (startup clock 2026-08-01).
        contractor = create_qualified_contractor(insurance_expiry_date="2026-08-10T00:00:00Z")
        engagement = create_engagement_record(sc["project"]["id"], contractor["id"])
        get_success_data(
            api.acknowledge_rules(
                engagement["id"], make_contractor_rep_headers(contractor["id"])
            )
        )
        # The policy lapses before the landlord approves.
        set_logical_clock("2026-08-15T00:00:00Z")

        resp = api.approve_engagement(engagement["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_EXPIRED)

    def test_engagement_approve_unqualified_contractor_rejected(self, api, landlord_pm_headers):
        """PRD 3.4: "the landlord's approval moves the engagement `PROPOSED` →
        `APPROVED` through the three-check ladder of §2.7: acknowledgement
        (`ERR_BUILDING_RULES_NOT_ACKNOWLEDGED`), insurance currency at the
        logical clock (`ERR_INSURANCE_EXPIRED`), and the firm's `QUALIFIED`
        standing (`ERR_CONTRACTOR_NOT_QUALIFIED`)."

        Design: Corner/validations/engagement_approve_unqualified_contractor_rejected
        """
        sc = setup_project_in_pre_construction()
        contractor = create_contractor_record()  # never qualified: stays PENDING
        assert contractor["qualification_status"] == "PENDING"
        engagement = create_engagement_record(sc["project"]["id"], contractor["id"])
        get_success_data(
            api.acknowledge_rules(
                engagement["id"], make_contractor_rep_headers(contractor["id"])
            )
        )

        resp = api.approve_engagement(engagement["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_NOT_QUALIFIED)


class TestEngagementTermination:
    def test_engagement_terminate_with_confirmed_milestone_rejected(
        self, api, landlord_pm_headers
    ):
        """PRD 3.4: "Termination from `PROPOSED`, `APPROVED`, or `ACTIVE` into
        `TERMINATED` is refused while the engagement holds any `CONFIRMED`
        milestone, and terminating an `ACTIVE` engagement cancels its `PLANNED`
        milestones in the same write." PRD 3.4: "The landlord may cancel a
        milestone from `PLANNED` or `CONFIRMED` into `CANCELLED`."

        Design: Corner/errors/engagement_terminate_with_confirmed_milestone_rejected
        """
        sc = setup_project_in_construction()
        engagement = sc["engagement"]
        milestone = create_milestone_record(
            engagement["id"],
            sc["contractor"]["id"],
            milestone_name="Noisy",
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-20T00:00:00Z",
            work_type="NOISY",
        )
        milestone = get_success_data(api.confirm_milestone(milestone["id"], landlord_pm_headers))
        assert milestone["status"] == "CONFIRMED"

        resp = api.terminate_engagement(engagement["id"], landlord_pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        cancelled = get_success_data(api.cancel_milestone(milestone["id"], landlord_pm_headers))
        assert cancelled["status"] == "CANCELLED"
        terminated = validate_success(
            api.terminate_engagement(engagement["id"], landlord_pm_headers), 200
        )
        assert terminated["status"] == "TERMINATED", (
            "with no CONFIRMED milestone remaining, termination must succeed"
        )
