"""State machine transitions, cycles, invalid transitions, terminal lockdown, and initial state.

Covers the non-linear-state-machine difficulty rule plus the state_machines corner instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_org_active_sub_site, setup_completed_scan, setup_subscription_past_due,
    create_running_scan, complete_scan_with_findings, list_findings_for_scan,
    drive_task_to_submitted, record_retest, reopen_finding, resolve_finding, create_task,
    create_queued_scan, file_legal_demand,
    create_org, add_site, create_legal_demand_payload, activate_subscription_payload,
    finding_entry, TEST_USERS, make_org_admin_headers,
)
from test_helpers import api_client


class TestRemediationRevisionCycle:
    def test_reopened_finding_returns_to_in_remediation_via_supersede(self, api, remediation_vendor_headers):
        """PRD §3.3: "A REOPENED finding re-enters remediation through a superseding task. The
        vendor creates a new remediation task that names the prior rejected task in its
        supersedes_task_id; ... The new task is created in ASSIGNED with its supersedes_task_id
        set, the superseded task moves as a system-driven transition from REJECTED to the
        terminal SUPERSEDED status, the finding moves from REOPENED back to IN_REMEDIATION, and
        the finding's version advances."

        FAIL retest -> REOPENED; superseding task -> finding IN_REMEDIATION, prior task SUPERSEDED.

        Design: Difficulty/non_linear_state_machine/finding_remediation_revision_cycle
        """
        org, sub, site, scan = setup_completed_scan([finding_entry("1.4.3", "CRITICAL")],
                                                    tier="SCAN", audited_page_count=10)
        finding = list_findings_for_scan(scan["id"])[0]
        t1 = reopen_finding(finding["id"])  # finding now REOPENED, t1 REJECTED
        t2 = create_task(finding["id"], supersedes_task_id=t1["id"], vendor="vendor-2", effort=5)

        f_after = validate_success(api.get_finding(finding["id"], TEST_USERS["audit_engineer_headers"]), 200)
        t1_after = validate_success(api.get_remediation_task(t1["id"], TEST_USERS["audit_engineer_headers"]), 200)
        assert f_after["status"] == "IN_REMEDIATION"
        assert t1_after["status"] == "SUPERSEDED"

    def test_superseding_task_records_supersedes_pointer(self, api, remediation_vendor_headers):
        """PRD §3.3: "The supersedes_task_id is null for the first task on any finding and is set
        only for these superseding tasks."

        The superseding task carries supersedes_task_id pointing at the prior rejected task.

        Design: Difficulty/non_linear_state_machine/finding_remediation_revision_cycle
        """
        org, sub, site, scan = setup_completed_scan([finding_entry("1.4.3", "CRITICAL")],
                                                    tier="SCAN", audited_page_count=10)
        finding = list_findings_for_scan(scan["id"])[0]
        t1 = reopen_finding(finding["id"])
        t2 = create_task(finding["id"], supersedes_task_id=t1["id"], vendor="vendor-2", effort=5)
        assert t2["supersedes_task_id"] == t1["id"]


class TestSubscriptionCycle:
    def test_past_due_returns_to_active(self, api, org_admin_headers):
        """PRD §3.1: "An OrgAdmin activates a subscription, taking it from TRIAL to ACTIVE or,
        after a lapse, from PAST_DUE back to ACTIVE; this is the cyclic path that lets a recovered
        account resume."

        ACTIVE -> PAST_DUE -> ACTIVE back-edge.

        Design: Difficulty/non_linear_state_machine/subscription_past_due_active_cycle
        """
        org, past_due, site = setup_subscription_past_due()
        assert past_due["status"] == "PAST_DUE"
        owner = make_org_admin_headers(org["id"])
        reactivated = validate_success(
            api.activate_subscription(past_due["id"],
                                      activate_subscription_payload(past_due["version"]), owner), 200)
        assert reactivated["status"] == "ACTIVE"

    def test_active_to_past_due_transition(self, api, platform_admin_headers):
        """PRD §3.1: "A PlatformAdmin may move an ACTIVE subscription to PAST_DUE".

        ACTIVE -> PAST_DUE forward edge of the cycle.

        Design: Difficulty/non_linear_state_machine/subscription_past_due_active_cycle
        """
        org, sub, site = setup_org_active_sub_site(tier="SCAN", audited_page_count=5)
        assert sub["status"] == "ACTIVE"
        past_due = validate_success(
            api.mark_past_due_subscription(sub["id"], TEST_USERS["platform_admin_headers"]), 200)
        assert past_due["status"] == "PAST_DUE"


class TestInvalidTransitions:
    def test_cancel_running_scan_rejected(self, api, audit_engineer_headers):
        """PRD §3.2: "From QUEUED, a scan may instead be cancelled, moving it to the terminal
        CANCELLED status."
        PRD §3.2: "only the transition out of the documented from status is legal — any other
        starting status yields ERR_INVALID_STATE." (general rule applied to scan cancel)

        cancel is valid only from QUEUED; on a RUNNING scan it returns ERR_INVALID_STATE.

        Design: Corner/state_machines/cancel_scan_from_running_returns_invalid_state
        """
        org, sub, site = setup_org_active_sub_site(tier="SCAN", audited_page_count=5)
        scan = create_running_scan(site["id"], wcag_target_level="A")
        res = api.cancel_scan(scan["id"], TEST_USERS["audit_engineer_headers"])
        validate_error(res, "ERR_INVALID_STATE")

    def test_resolve_received_legal_demand_rejected(self, api, compliance_manager_headers):
        """PRD §3.6: "The demand is resolved by a ComplianceManager from either RESPONDING or
        ESCALATED, moving it to the terminal RESOLVED status."
        PRD §3.6: "a demand that is not in the documented from status for the requested move is
        rejected with ERR_INVALID_STATE."

        resolve requires RESPONDING/ESCALATED; on a RECEIVED demand -> ERR_INVALID_STATE.

        Design: Corner/state_machines/legal_resolve_from_received_returns_invalid_state
        """
        org = create_org()
        site = add_site(org["id"], audited_page_count=5)
        ld = file_legal_demand(site["id"], claimant_name="X")
        assert ld["status"] == "RECEIVED"
        res = api.resolve_legal_demand(ld["id"], TEST_USERS["compliance_manager_headers"])
        validate_error(res, "ERR_INVALID_STATE")

    def test_accept_risk_on_resolved_finding_rejected(self, api, compliance_manager_headers):
        """PRD §3.7: "A ComplianceManager accepts the risk on a finding that is OPEN, moving it
        directly to the terminal WONT_FIX_ACCEPTED status".
        PRD §3.3: "Any of these transitions attempted against a finding or task that is not in the
        required starting state is rejected with ERR_INVALID_STATE."

        accept-risk requires OPEN; a RESOLVED (terminal) finding -> ERR_INVALID_STATE.

        Design: Corner/state_machines/terminal_resolved_finding_cannot_accept_risk
        """
        org, sub, site, scan = setup_completed_scan([finding_entry("1.4.3", "CRITICAL")],
                                                    tier="SCAN", audited_page_count=5)
        finding = list_findings_for_scan(scan["id"])[0]
        resolve_finding(finding["id"])
        f_after = validate_success(api.get_finding(finding["id"], TEST_USERS["audit_engineer_headers"]), 200)
        assert f_after["status"] == "RESOLVED"
        res = api.accept_risk_finding(finding["id"], TEST_USERS["compliance_manager_headers"])
        validate_error(res, "ERR_INVALID_STATE")


class TestInitialStateAndPreconditions:
    def test_new_scan_is_queued_version_one(self, api, audit_engineer_headers):
        """PRD §3.2: "A scan is queued by naming its site_id and a wcag_target_level of A, AA, or
        AAA; it begins in the QUEUED status."
        PRD §2.4: "an integer version that begins at 1 and increments by exactly one on every
        mutation that changes the resource."

        A freshly created scan is QUEUED with version 1.

        Design: Corner/state_machines/newly_created_scan_starts_queued
        """
        org = create_org()
        site = add_site(org["id"], audited_page_count=5)
        scan = validate_success(api.create_scan(
            {"site_id": site["id"], "wcag_target_level": "AA"}, TEST_USERS["audit_engineer_headers"]), 201)
        assert scan["status"] == "QUEUED"
        assert scan["version"] == 1
