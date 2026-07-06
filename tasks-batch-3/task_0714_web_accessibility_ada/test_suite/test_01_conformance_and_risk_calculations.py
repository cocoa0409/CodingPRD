"""Conformance scoring, risk exposure, invoice, and credit calculations.

Covers the dual-variant and combinatorial-formula difficulty rules plus the
correct-result corner instance for conformance scoring.
"""
import pytest

from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_org_active_sub_site, setup_completed_scan, setup_issued_vpat_single_critical_resolved,
    setup_org_with_n_sites, list_findings_for_scan, create_running_scan,
    complete_scan_with_findings, resolve_finding, drive_task_to_submitted, record_retest,
    create_draft_vpat, scan_version, file_legal_demand,
    finding_entry, activate_subscription_payload, issue_vpat_payload,
    TEST_USERS, make_org_admin_headers,
)


def _findings_3_critical_serious_moderate():
    return [
        finding_entry("1.4.3", "CRITICAL"),
        finding_entry("1.1.1", "SERIOUS"),
        finding_entry("2.4.4", "MODERATE"),
    ]


class TestDualVariantConformance:
    def test_provisional_score_zero_when_all_findings_open_at_completion(self, api, audit_engineer_headers):
        """PRD §2.6: "the provisional variant (frozen at scan completion onto the scan's
        provisional_conformance_score) treats only RESOLVED findings as passed and does not
        count WONT_FIX_ACCEPTED".
        PRD §2.6: "When the total weight is zero, the score is exactly 100.00; otherwise the
        score is 100 multiplied by the passed weight, divided by the total weight, rounded
        half-up to two decimal places."

        With all three findings OPEN at completion, passed_weight == 0, so the frozen
        provisional score is 0.00.

        Design: Difficulty/dual_variant_calc/conformance_provisional_vs_certified_diverge
        """
        org, sub, site, scan = setup_completed_scan(_findings_3_critical_serious_moderate())
        assert scan["provisional_conformance_score"] == pytest.approx(0.00, abs=0.001)

    def test_certified_score_counts_resolved_and_accepted_risk(self, api, compliance_manager_headers):
        """PRD §2.6: "the certified variant (frozen at VPAT issuance onto the report's
        certified_conformance_score) treats both RESOLVED and WONT_FIX_ACCEPTED findings as
        passed, so an accepted-risk finding counts as conformant for certification but not for
        the provisional snapshot."
        PRD §2.6: "a CRITICAL finding weighs 10, a SERIOUS finding weighs 5, a MODERATE finding
        weighs 2, and a MINOR finding weighs 1."

        CRITICAL(10) RESOLVED + SERIOUS(5) WONT_FIX_ACCEPTED pass; MODERATE(2) stays OPEN.
        certified = 100 * 15/17 = 88.24; level WCAG_AA_PARTIAL (>=80, <95).

        Design: Difficulty/dual_variant_calc/conformance_provisional_vs_certified_diverge
        """
        org, sub, site, scan = setup_completed_scan(_findings_3_critical_serious_moderate())
        findings = list_findings_for_scan(scan["id"])
        crit = next(f for f in findings if f["severity"] == "CRITICAL")
        ser = next(f for f in findings if f["severity"] == "SERIOUS")

        resolve_finding(crit["id"])
        get_success_data(api.accept_risk_finding(ser["id"], TEST_USERS["compliance_manager_headers"]))

        vpat = create_draft_vpat(site["id"], scan["id"])
        sv = scan_version(scan["id"])
        issued = validate_success(
            api.issue_vpat_report(vpat["id"], issue_vpat_payload(sv),
                                  TEST_USERS["compliance_manager_headers"]), 200)
        assert issued["certified_conformance_score"] == pytest.approx(88.24, abs=0.001)
        assert issued["conformance_level"] == "WCAG_AA_PARTIAL"

    def test_certified_full_score_when_all_resolved(self, api, compliance_manager_headers):
        """PRD §2.6: "When the total weight is zero, the score is exactly 100.00; otherwise the
        score is 100 multiplied by the passed weight, divided by the total weight, rounded
        half-up to two decimal places."
        PRD §3.4: "The level is WCAG_AA_FULL when the certified score is at least 95".

        A single CRITICAL finding resolved -> passed_weight == total_weight -> 100.00 -> FULL.

        Design: Corner/calculations/empty_scan_findings_all_resolved_gives_full_score
        """
        org, site, scan, issued = setup_issued_vpat_single_critical_resolved()
        assert issued["certified_conformance_score"] == pytest.approx(100.00, abs=0.001)
        assert issued["conformance_level"] == "WCAG_AA_FULL"


class TestRiskExposureCurrentVsProjected:
    def test_current_risk_counts_all_nonterminal_findings(self, api, compliance_manager_headers):
        """PRD §3.7: "for the current variant, the open set is every non-terminal finding —
        those in OPEN, IN_REMEDIATION, RETEST_PENDING, or REOPENED".
        PRD §3.7: "A base figure is the smaller of 100 and the quantity 8 times the critical
        count plus 3 times the serious count."

        Two CRITICAL findings, one with an IN_PROGRESS task (still non-terminal): current
        counts both -> base = 8*2 = 16, no overdue, no legal -> current = 16.00.

        Design: Difficulty/dual_variant_calc/risk_current_vs_projected_diverge
        """
        org, sub, site, scan = setup_completed_scan(
            [finding_entry("1.4.3", "CRITICAL"), finding_entry("2.1.1", "CRITICAL")])
        findings = list_findings_for_scan(scan["id"])
        # Put one finding's task in IN_PROGRESS (create + begin, do not submit).
        task = get_success_data(api.create_remediation_task(
            {"finding_id": findings[0]["id"], "assigned_vendor_id": "vendor-1",
             "estimated_effort_hours": 3}, TEST_USERS["remediation_vendor_headers"]))
        get_success_data(api.begin_remediation_task(task["id"], TEST_USERS["remediation_vendor_headers"]))

        proj = validate_success(
            api.get_site_risk_projection(site["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert proj["current_risk_exposure_score"] == pytest.approx(16.00, abs=0.001)

    def test_projected_risk_excludes_in_progress_task_findings(self, api, compliance_manager_headers):
        """PRD §3.7: "The projection assumes that any finding currently backed by a remediation
        task in IN_PROGRESS or SUBMITTED status will close: such findings are excluded from the
        open set, so the critical and serious counts drop accordingly".
        PRD §3.7: "A base figure is the smaller of 100 and the quantity 8 times the critical
        count plus 3 times the serious count."

        One of two CRITICAL findings has an IN_PROGRESS task -> projected excludes it -> base
        = 8*1 = 8.00.

        Design: Difficulty/dual_variant_calc/risk_current_vs_projected_diverge
        """
        org, sub, site, scan = setup_completed_scan(
            [finding_entry("1.4.3", "CRITICAL"), finding_entry("2.1.1", "CRITICAL")])
        findings = list_findings_for_scan(scan["id"])
        task = get_success_data(api.create_remediation_task(
            {"finding_id": findings[0]["id"], "assigned_vendor_id": "vendor-1",
             "estimated_effort_hours": 3}, TEST_USERS["remediation_vendor_headers"]))
        get_success_data(api.begin_remediation_task(task["id"], TEST_USERS["remediation_vendor_headers"]))

        proj = validate_success(
            api.get_site_risk_projection(site["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert proj["projected_risk_exposure_score"] == pytest.approx(8.00, abs=0.001)


class TestCombinatorialFormulas:
    def test_risk_exposure_nonlinear_with_legal_bump(self, api, compliance_manager_headers):
        """PRD §3.7: "The raw score is the base multiplied by the overdue factor, plus the legal
        bump; the stored risk_exposure_score is the smaller of 100.0 and that raw value, rounded
        half-up to two decimal places."
        PRD §3.7: "A legal bump of 25 is added when the site has any active legal demand (status
        RECEIVED, RESPONDING, or ESCALATED) and 0 otherwise."

        C=1 (CRITICAL), S=1 (SERIOUS), no overdue (factor 1), legal RECEIVED (bump 25):
        raw = (8*1 + 3*1) * 1 + 25 = 36.00; posture BLOCKED.

        Design: Difficulty/combinatorial_formula/risk_exposure_nonlinear_three_inputs
        """
        org, sub, site, scan = setup_completed_scan(
            [finding_entry("1.4.3", "CRITICAL"), finding_entry("1.1.1", "SERIOUS")],
            audited_page_count=30)
        file_legal_demand(site["id"], claimant_name="Doe")
        refreshed = validate_success(
            api.get_site(site["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert refreshed["risk_exposure_score"] == pytest.approx(36.00, abs=0.001)
        assert refreshed["audit_posture"] == "BLOCKED"

    def test_risk_exposure_nonlinear_two_critical_with_legal(self, api, compliance_manager_headers):
        """PRD §3.7: "A base figure is the smaller of 100 and the quantity 8 times the critical
        count plus 3 times the serious count."
        PRD §3.7: "The raw score is the base multiplied by the overdue factor, plus the legal
        bump; the stored risk_exposure_score is the smaller of 100.0 and that raw value, rounded
        half-up to two decimal places."

        Second nonlinear combination: C=2, S=0, no overdue (factor 1), legal bump 25 ->
        raw = (8*2) * 1 + 25 = 41.00.

        Design: Difficulty/combinatorial_formula/risk_exposure_nonlinear_three_inputs
        """
        org, sub, site, scan = setup_completed_scan(
            [finding_entry("1.4.3", "CRITICAL"), finding_entry("2.1.1", "CRITICAL")],
            audited_page_count=30)
        file_legal_demand(site["id"], claimant_name="Doe")
        refreshed = validate_success(
            api.get_site(site["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert refreshed["risk_exposure_score"] == pytest.approx(41.00, abs=0.001)

    def test_subscription_invoice_round_per_site_then_sum(self, api, org_admin_headers):
        """PRD §3.1: "for each site, the system takes the tier fee plus the per-page charge times
        that site's page count, multiplies by one minus the applicable discount, and rounds that
        single site's fee half-up to whole cents; only after every site's fee has been
        individually rounded are the rounded fees summed to produce monthly_invoice_cents."
        PRD §3.1: "the discount is 15 percent when the organization has at least 10 sites, 10
        percent when it has at least 5 sites (but fewer than 10), and 0 otherwise."

        Five MONITOR sites (fee 24900 + 5/page), 10% discount, pages [120,333,87,1000,55]:
        per-site rounded then summed = 119229.

        Design: Difficulty/combinatorial_formula/subscription_invoice_round_per_site_then_sum
        """
        org, sub, sites = setup_org_with_n_sites([120, 333, 87, 1000, 55], tier="MONITOR")
        owner = make_org_admin_headers(org["id"])
        activated = validate_success(
            api.activate_subscription(sub["id"], activate_subscription_payload(sub["version"]), owner), 200)
        assert activated["monthly_invoice_cents"] == 119229
        assert activated["status"] == "ACTIVE"

    def test_subscription_invoice_single_site_no_discount(self, api, org_admin_headers):
        """PRD §3.1: "The base tier fee in cents is 9,900 for SCAN, 24,900 for MONITOR, and
        49,900 for MANAGED. On top of the tier fee, each audited page adds a per-page charge in
        cents of 0 for SCAN, 5 for MONITOR, and 12 for MANAGED, multiplied by that site's
        audited_page_count."
        PRD §3.1: "the discount is 15 percent when the organization has at least 10 sites, 10
        percent when it has at least 5 sites (but fewer than 10), and 0 otherwise."

        Second invoice test, no-discount tier: one MONITOR site of 120 pages -> 24900 + 5*120 =
        25500, discount 0 -> monthly_invoice_cents 25500.

        Design: Difficulty/combinatorial_formula/subscription_invoice_round_per_site_then_sum
        """
        org, sub, sites = setup_org_with_n_sites([120], tier="MONITOR")
        owner = make_org_admin_headers(org["id"])
        activated = validate_success(
            api.activate_subscription(sub["id"], activate_subscription_payload(sub["version"]), owner), 200)
        assert activated["monthly_invoice_cents"] == 25500

    def test_vpat_credit_keyed_on_derived_level(self, api, compliance_manager_headers):
        """PRD §3.4: "first the certified score is computed, then the conformance level is
        derived from it, and then a remediation credit keyed on that level is added to the owning
        organization's account_credit_cents."
        PRD §3.4: "The credit, in cents, is 0 for WCAG_AA_FULL, 2,500 for WCAG_AA_PARTIAL, 5,000
        for WCAG_A, and 10,000 for NON_CONFORMANT."

        certified=88.24 -> level WCAG_AA_PARTIAL -> credit 2500 added to org credit.

        Design: Difficulty/combinatorial_formula/vpat_credit_circular_evaluation_order
        """
        org, sub, site, scan = setup_completed_scan(_findings_3_critical_serious_moderate(),
                                                    audited_page_count=40)
        findings = list_findings_for_scan(scan["id"])
        crit = next(f for f in findings if f["severity"] == "CRITICAL")
        ser = next(f for f in findings if f["severity"] == "SERIOUS")
        resolve_finding(crit["id"])
        get_success_data(api.accept_risk_finding(ser["id"], TEST_USERS["compliance_manager_headers"]))
        vpat = create_draft_vpat(site["id"], scan["id"])
        sv = scan_version(scan["id"])
        issued = validate_success(
            api.issue_vpat_report(vpat["id"], issue_vpat_payload(sv),
                                  TEST_USERS["compliance_manager_headers"]), 200)
        assert issued["conformance_level"] == "WCAG_AA_PARTIAL"

        org_after = validate_success(
            api.get_organization(org["id"], TEST_USERS["compliance_manager_headers"]), 200)
        assert org_after["account_credit_cents"] == 2500

    def test_vpat_credit_conformance_level_partial(self, api, compliance_manager_headers):
        """PRD §3.4: "The level is WCAG_AA_FULL when the certified score is at least 95,
        WCAG_AA_PARTIAL when it is at least 80 (but below 95), WCAG_A when it is at least 50 (but
        below 80), and NON_CONFORMANT otherwise; the tier boundaries 95, 80, and 50 are inclusive
        lower bounds."

        Second test of the same instance, asserting the derived level field directly on the
        issued report (88.24 -> WCAG_AA_PARTIAL).

        Design: Difficulty/combinatorial_formula/vpat_credit_circular_evaluation_order
        """
        org, sub, site, scan = setup_completed_scan(_findings_3_critical_serious_moderate(),
                                                    audited_page_count=40)
        findings = list_findings_for_scan(scan["id"])
        crit = next(f for f in findings if f["severity"] == "CRITICAL")
        ser = next(f for f in findings if f["severity"] == "SERIOUS")
        resolve_finding(crit["id"])
        get_success_data(api.accept_risk_finding(ser["id"], TEST_USERS["compliance_manager_headers"]))
        vpat = create_draft_vpat(site["id"], scan["id"])
        sv = scan_version(scan["id"])
        issued = validate_success(
            api.issue_vpat_report(vpat["id"], issue_vpat_payload(sv),
                                  TEST_USERS["compliance_manager_headers"]), 200)
        assert issued["certified_conformance_score"] == pytest.approx(88.24, abs=0.001)
        assert issued["conformance_level"] == "WCAG_AA_PARTIAL"
