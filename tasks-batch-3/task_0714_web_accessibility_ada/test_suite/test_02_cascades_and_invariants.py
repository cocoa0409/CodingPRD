"""Cascade chains and compensating invariants.

Covers the transitive-cascade and compensating-invariant difficulty rules, plus the
second test of the combinatorial risk-exposure instance.
"""
import pytest

from test_helpers import (
    validate_success, get_success_data,
    setup_org_active_sub_site, setup_completed_scan, setup_granted_certification,
    create_running_scan, complete_scan_with_findings, list_findings_for_scan,
    file_legal_demand, respond_legal_demand, resolve_legal_demand,
    finding_entry, TEST_USERS,
)


class TestScanCompleteCascade:
    def test_scan_complete_cascades_posture_and_risk(self, api, audit_engineer_headers):
        """PRD §3.2: "the parent site's audit_posture is recomputed from the freshly emitted
        findings (a previously UNSCANNED site moves to AT_RISK if open findings exist, or to
        CLEAN if none do), and then the site's risk_exposure_score is recomputed by the current
        variant."
        PRD §3.7: "A base figure is the smaller of 100 and the quantity 8 times the critical
        count plus 3 times the serious count."

        CRITICAL + SERIOUS open at completion -> posture AT_RISK, risk = 8*1 + 3*1 = 11.00.

        Design: Difficulty/transitive_cascade/scan_complete_cascade_depth3
        """
        org, sub, site = setup_org_active_sub_site(audited_page_count=20)
        assert site["audit_posture"] == "UNSCANNED"
        assert site["risk_exposure_score"] == pytest.approx(0.0, abs=0.001)

        scan = create_running_scan(site["id"])
        complete_scan_with_findings(
            scan["id"], [finding_entry("1.4.3", "CRITICAL"), finding_entry("1.1.1", "SERIOUS")])
        refreshed = validate_success(api.get_site(site["id"], TEST_USERS["audit_engineer_headers"]), 200)
        assert refreshed["audit_posture"] == "AT_RISK"
        assert refreshed["risk_exposure_score"] == pytest.approx(11.00, abs=0.001)

    def test_scan_complete_cascade_visible_immediately(self, api, audit_engineer_headers):
        """PRD §2.5: "When a single operation changes a derived field's inputs, the server
        recomputes that field as part of the same operation, and any downstream field that
        depends on it is recomputed in turn, in a fixed order."
        PRD §3.2: "the parent site's audit_posture is recomputed from the freshly emitted
        findings (a previously UNSCANNED site moves to AT_RISK if open findings exist...".

        The recomputed posture is observable on the very next GET of the site.

        Design: Difficulty/transitive_cascade/scan_complete_cascade_depth3
        """
        org, sub, site = setup_org_active_sub_site(audited_page_count=20)
        scan = create_running_scan(site["id"])
        complete_scan_with_findings(scan["id"], [finding_entry("1.4.3", "CRITICAL")])
        refreshed = validate_success(api.get_site(site["id"], TEST_USERS["audit_engineer_headers"]), 200)
        assert refreshed["audit_posture"] == "AT_RISK"


class TestLegalResolveCascade:
    def test_legal_resolve_unblocks_and_recomputes(self, api, compliance_manager_headers):
        """PRD §3.6: "Both resolution and dismissal close the block-and-unblock cycle by
        recomputing, in order, the organization's open_legal_demand_count, then the affected
        site's audit_posture (which leaves BLOCKED for AT_RISK or CLEAN once no active demand
        remains on the site), then the site's risk_exposure_score (whose legal bump drops to 0
        once no active demand remains)."

        After resolve: org open count 0, site AT_RISK, risk back to 11.00 (CRITICAL+SERIOUS,
        legal bump removed).

        Design: Difficulty/transitive_cascade/legal_resolve_cascade_depth3
        """
        org, sub, site, scan = setup_completed_scan(
            [finding_entry("1.4.3", "CRITICAL"), finding_entry("1.1.1", "SERIOUS")],
            audited_page_count=30)
        ld = file_legal_demand(site["id"], claimant_name="Roe")
        respond_legal_demand(ld["id"])
        resolve_legal_demand(ld["id"])

        site_after = validate_success(api.get_site(site["id"], TEST_USERS["compliance_manager_headers"]), 200)
        org_after = validate_success(
            api.get_organization(org["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert org_after["open_legal_demand_count"] == 0
        assert site_after["audit_posture"] == "AT_RISK"
        assert site_after["risk_exposure_score"] == pytest.approx(11.00, abs=0.001)

    def test_legal_demand_create_blocks_and_bumps_risk(self, api, compliance_manager_headers):
        """PRD §3.6: "On creation the demand enters the RECEIVED status and immediately triggers
        the third cascade chain of §2.5: the owning organization's open_legal_demand_count is
        recomputed, the named site's audit_posture is driven to BLOCKED, and the site's
        risk_exposure_score is recomputed with the legal bump (described in §3.7) added."
        PRD §3.7: "A legal bump of 25 is added when the site has any active legal demand (status
        RECEIVED, RESPONDING, or ESCALATED) and 0 otherwise."

        Forward leg of the depth-3 legal cascade: filing the demand drives the site from risk
        11.00 to 36.00 and posture BLOCKED, and org open count to 1.

        Design: Difficulty/transitive_cascade/legal_resolve_cascade_depth3
        """
        org, sub, site, scan = setup_completed_scan(
            [finding_entry("1.4.3", "CRITICAL"), finding_entry("1.1.1", "SERIOUS")],
            audited_page_count=30)
        file_legal_demand(site["id"], claimant_name="Roe")
        site_after = validate_success(api.get_site(site["id"], TEST_USERS["compliance_manager_headers"]), 200)
        org_after = validate_success(
            api.get_organization(org["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert site_after["audit_posture"] == "BLOCKED"
        assert site_after["risk_exposure_score"] == pytest.approx(36.00, abs=0.001)
        assert org_after["open_legal_demand_count"] == 1


class TestCompensatingInvariants:
    def test_legal_block_then_unblock_conserves_risk(self, api, compliance_manager_headers):
        """PRD §3.6: "On creation the demand enters the RECEIVED status and immediately triggers
        the third cascade chain of §2.5: ... the site's risk_exposure_score is recomputed with
        the legal bump (described in §3.7) added."
        PRD §3.6: "the site's risk_exposure_score (whose legal bump drops to 0 once no active
        demand remains)."

        Filing a demand adds the legal bump (11.00 -> 36.00); resolving removes it, restoring
        exactly 11.00 with no drift.

        Design: Difficulty/compensating_invariant/legal_block_unblock_conserves_risk_score
        """
        org, sub, site, scan = setup_completed_scan(
            [finding_entry("1.4.3", "CRITICAL"), finding_entry("1.1.1", "SERIOUS")],
            audited_page_count=30)
        before = validate_success(api.get_site(site["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert before["risk_exposure_score"] == pytest.approx(11.00, abs=0.001)

        ld = file_legal_demand(site["id"], claimant_name="Boe")
        blocked = validate_success(api.get_site(site["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert blocked["risk_exposure_score"] == pytest.approx(36.00, abs=0.001)

        respond_legal_demand(ld["id"])
        resolve_legal_demand(ld["id"])
        after = validate_success(api.get_site(site["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert after["risk_exposure_score"] == pytest.approx(11.00, abs=0.001)

    def test_risk_nonlinear_conserved_value_matches_prelegal(self, api, compliance_manager_headers):
        """PRD §3.7: "The raw score is the base multiplied by the overdue factor, plus the legal
        bump; the stored risk_exposure_score is the smaller of 100.0 and that raw value, rounded
        half-up to two decimal places."
        PRD §3.7: "A legal bump of 25 is added when the site has any active legal demand (status
        RECEIVED, RESPONDING, or ESCALATED) and 0 otherwise."

        Second test of the conserved-quantity instance: with the demand active the score is the
        base 11.00 plus the 25 bump, i.e. 36.00 — confirming the bump magnitude is exactly the
        difference restored on resolve.

        Design: Difficulty/compensating_invariant/legal_block_unblock_conserves_risk_score
        """
        org, sub, site, scan = setup_completed_scan(
            [finding_entry("1.4.3", "CRITICAL"), finding_entry("1.1.1", "SERIOUS")],
            audited_page_count=30)
        ld = file_legal_demand(site["id"], claimant_name="Coe")
        blocked = validate_success(api.get_site(site["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert blocked["risk_exposure_score"] == pytest.approx(36.00, abs=0.001)

    def test_vpat_revoke_cascades_certification_to_revoked(self, api, compliance_manager_headers):
        """PRD §3.4: "Revocation cascades into certifications: any Certification whose
        vpat_report_id names this report and whose status is GRANTED is moved from GRANTED to
        REVOKED."

        Granting then revoking the backing VPAT moves the GRANTED certification to REVOKED,
        conserving the count of GRANTED certs at 0.

        Design: Difficulty/compensating_invariant/vpat_issue_revoke_conserves_certification_count
        """
        org, site, scan, vpat, cert = setup_granted_certification()
        assert cert["status"] == "GRANTED"
        get_success_data(api.revoke_vpat_report(vpat["id"], TEST_USERS["compliance_manager_headers"]))
        cert_after = validate_success(
            api.get_certification(cert["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert cert_after["status"] == "REVOKED"

    def test_vpat_revoke_leaves_no_granted_cert_for_site(self, api, compliance_manager_headers):
        """PRD §3.4: "A ComplianceManager may revoke an ISSUED report, moving it to the terminal
        REVOKED status. Revocation cascades into certifications: any Certification whose
        vpat_report_id names this report and whose status is GRANTED is moved from GRANTED to
        REVOKED."

        Second test of the conserved-count instance: after VPAT revoke, listing the site's
        certifications shows none remaining in GRANTED.

        Design: Difficulty/compensating_invariant/vpat_issue_revoke_conserves_certification_count
        """
        from test_helpers import validate_paginated
        org, site, scan, vpat, cert = setup_granted_certification()
        get_success_data(api.revoke_vpat_report(vpat["id"], TEST_USERS["compliance_manager_headers"]))
        data, _meta = validate_paginated(api.list_certifications(
            TEST_USERS["compliance_manager_headers"], params={"site_id": site["id"], "limit": 100}))
        granted = [c for c in data if c["status"] == "GRANTED"]
        assert len(granted) == 0
