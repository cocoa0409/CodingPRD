"""Validation priority pairs, cross-entity state dependencies, boundary precision,
resource uniqueness, and business-rule violations.

Covers difficulty rules priority_pair_validation_conflict, boundary_precision_check,
cross_entity_state_dependency, resource_temporal_overlap, plus validations corner instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_org_active_sub_site, setup_completed_scan, setup_subscription_suspended,
    setup_issued_vpat_single_critical_resolved, setup_granted_certification,
    setup_training_in_progress,
    create_running_scan, create_queued_scan, complete_scan_with_findings, list_findings_for_scan,
    drive_task_to_submitted, file_legal_demand, set_clock,
    create_org, add_site, create_org_with_trial_subscription,
    create_subscription_payload, create_site_payload, create_scan_payload,
    complete_training_payload, finding_entry,
    TEST_USERS, make_org_admin_headers,
)


class TestValidationPriorityPairs:
    def test_forbidden_role_beats_invalid_state(self, api, remediation_vendor_headers):
        """PRD §2.11: "Authentication (ERR_UNAUTHENTICATED) is checked first, then role
        authorization (ERR_FORBIDDEN_ROLE), then existence of every referenced resource
        (ERR_RESOURCE_NOT_FOUND), then foreign-key consistency on the create paths that require it
        (ERR_FK_MISMATCH). Next comes the state check that the target is in a state valid for the
        requested transition (ERR_INVALID_STATE)".
        PRD §2.11: "a forbidden role surfaces as ERR_FORBIDDEN_ROLE even if the body is also
        malformed."

        A RemediationVendor (forbidden for complete) calling complete on a QUEUED scan (also
        state-invalid) gets the higher-priority ERR_FORBIDDEN_ROLE.

        Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state
        """
        org, sub, site = setup_org_active_sub_site(audited_page_count=20)
        scan = create_queued_scan(site["id"])
        res = api.complete_scan(
            scan["id"], {"findings": [finding_entry("1.4.3", "CRITICAL")]},
            TEST_USERS["remediation_vendor_headers"])
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_forbidden_role_surfaces_when_only_role_fails(self, api, remediation_vendor_headers):
        """PRD §2.11: "then role authorization (ERR_FORBIDDEN_ROLE)".
        PRD §2.11: "a forbidden role surfaces as ERR_FORBIDDEN_ROLE even if the body is also
        malformed."

        Isolating the higher-priority member of the pair: a RemediationVendor calling complete on
        a RUNNING scan (state-valid for complete) still gets ERR_FORBIDDEN_ROLE because the role
        check precedes the (now-passing) state check.

        Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state
        """
        org, sub, site = setup_org_active_sub_site(audited_page_count=20)
        scan = create_running_scan(site["id"])
        res = api.complete_scan(
            scan["id"], {"findings": [finding_entry("1.4.3", "CRITICAL")]},
            TEST_USERS["remediation_vendor_headers"])
        validate_error(res, "ERR_FORBIDDEN_ROLE")

    def test_invalid_state_beats_empty_findings(self, api, audit_engineer_headers):
        """PRD §2.11: "Next comes the state check that the target is in a state valid for the
        requested transition (ERR_INVALID_STATE) ... the non-empty-findings requirement for scan
        completion (ERR_EMPTY_FINDINGS)".

        complete on a QUEUED scan (state-invalid) with empty findings[] returns the
        higher-priority ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_empty_findings
        """
        org, sub, site = setup_org_active_sub_site(tier="SCAN", audited_page_count=8)
        scan = create_queued_scan(site["id"], wcag_target_level="A")
        res = api.complete_scan(scan["id"], {"findings": []}, TEST_USERS["audit_engineer_headers"])
        validate_error(res, "ERR_INVALID_STATE")

    def test_empty_findings_surfaces_when_state_valid(self, api, audit_engineer_headers):
        """PRD §2.11: "the non-empty-findings requirement for scan completion (ERR_EMPTY_FINDINGS)".
        PRD §3.2: "an empty findings payload is rejected with ERR_EMPTY_FINDINGS."

        Isolating the lower-priority member: on a RUNNING scan (state-valid for complete) an empty
        findings[] surfaces as ERR_EMPTY_FINDINGS once the masking state error no longer applies.

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_empty_findings
        """
        org, sub, site = setup_org_active_sub_site(tier="SCAN", audited_page_count=8)
        scan = create_running_scan(site["id"], wcag_target_level="A")
        res = api.complete_scan(scan["id"], {"findings": []}, TEST_USERS["audit_engineer_headers"])
        validate_error(res, "ERR_EMPTY_FINDINGS")


class TestBoundaryPrecision:
    def test_not_overdue_at_exact_sla_boundary(self, api, audit_engineer_headers):
        """PRD §3.2: "Each emitted finding's deadline, sla_due_at, is frozen at emission as the
        scan's completed_at plus a severity-specific number of hours: 72 hours for CRITICAL".
        PRD §3.2: "A finding also exposes a derived is_overdue flag, which is true when the
        logical clock now is strictly past sla_due_at and the finding's status is neither RESOLVED
        nor WONT_FIX_ACCEPTED; at the exact instant the clock equals sla_due_at the finding is not
        yet overdue, because the comparison is strict."

        Completion at default 2026-03-01T00:00:00Z -> CRITICAL due 2026-03-04T00:00:00Z; at clock
        exactly == due_at, is_overdue is False.

        Design: Difficulty/boundary_precision_check/overdue_strict_greater_than_at_sla_boundary
        """
        org, sub, site, scan = setup_completed_scan([finding_entry("1.4.3", "CRITICAL")],
                                                    tier="SCAN", audited_page_count=6)
        finding = list_findings_for_scan(scan["id"])[0]
        set_clock("2026-03-04T00:00:00Z")
        f_after = validate_success(api.get_finding(finding["id"], TEST_USERS["audit_engineer_headers"]), 200)
        assert f_after["is_overdue"] is False

    def test_overdue_true_one_hour_past_sla_boundary(self, api, audit_engineer_headers):
        """PRD §3.2: "A finding also exposes a derived is_overdue flag, which is true when the
        logical clock now is strictly past sla_due_at and the finding's status is neither RESOLVED
        nor WONT_FIX_ACCEPTED".
        PRD §3.2: "Each emitted finding's deadline, sla_due_at, is frozen at emission as the
        scan's completed_at plus a severity-specific number of hours: 72 hours for CRITICAL".

        One hour past the CRITICAL deadline (2026-03-04T01:00:00Z > 2026-03-04T00:00:00Z) ->
        is_overdue True; the strict-greater side of the same boundary.

        Design: Difficulty/boundary_precision_check/overdue_strict_greater_than_at_sla_boundary
        """
        org, sub, site, scan = setup_completed_scan([finding_entry("1.4.3", "CRITICAL")],
                                                    tier="SCAN", audited_page_count=6)
        finding = list_findings_for_scan(scan["id"])[0]
        set_clock("2026-03-04T01:00:00Z")
        f_after = validate_success(api.get_finding(finding["id"], TEST_USERS["audit_engineer_headers"]), 200)
        assert f_after["is_overdue"] is True

    def test_empty_findings_on_running_scan_rejected(self, api, audit_engineer_headers):
        """PRD §3.2: "The request must carry a findings payload, and that payload must contain at
        least one entry; an empty findings payload is rejected with ERR_EMPTY_FINDINGS."

        Completing a RUNNING scan with a zero-length findings[] -> ERR_EMPTY_FINDINGS.

        Design: Difficulty/boundary_precision_check/empty_findings_zero_count_rejected_on_complete
        """
        org, sub, site = setup_org_active_sub_site(tier="SCAN", audited_page_count=7)
        scan = create_running_scan(site["id"], wcag_target_level="A")
        res = api.complete_scan(scan["id"], {"findings": []}, TEST_USERS["audit_engineer_headers"])
        validate_error(res, "ERR_EMPTY_FINDINGS")

    def test_single_nonempty_finding_completes_successfully(self, api, audit_engineer_headers):
        """PRD §3.2: "The request must carry a findings payload, and that payload must contain at
        least one entry; an empty findings payload is rejected with ERR_EMPTY_FINDINGS."
        PRD §3.2: "Completing a scan ... advances the scan from RUNNING to the terminal COMPLETED
        status."

        The non-empty side of the same count boundary: exactly one finding (count 1) is accepted
        and the scan reaches COMPLETED with finding_count 1.

        Design: Difficulty/boundary_precision_check/empty_findings_zero_count_rejected_on_complete
        """
        org, sub, site = setup_org_active_sub_site(tier="SCAN", audited_page_count=7)
        scan = create_running_scan(site["id"], wcag_target_level="A")
        completed = validate_success(api.complete_scan(
            scan["id"], {"findings": [finding_entry("1.4.3", "CRITICAL")]},
            TEST_USERS["audit_engineer_headers"]), 200)
        assert completed["status"] == "COMPLETED"
        assert completed["finding_count"] == 1


class TestCrossEntityStateDependency:
    def test_remediation_blocked_when_site_blocked_by_legal(self, api, remediation_vendor_headers):
        """PRD §3.3: "A task may only be opened when the parent site is not BLOCKED by an active
        legal demand; an attempt against a blocked site is rejected with
        ERR_SITE_BLOCKED_BY_LEGAL".

        Site BLOCKED by a RECEIVED legal demand -> creating a remediation task on its OPEN finding
        is rejected ERR_SITE_BLOCKED_BY_LEGAL.

        Design: Difficulty/cross_entity_state_dependency/remediation_blocked_when_site_blocked_by_legal
        """
        org, sub, site, scan = setup_completed_scan([finding_entry("1.4.3", "CRITICAL")],
                                                    audited_page_count=12)
        finding = list_findings_for_scan(scan["id"])[0]
        file_legal_demand(site["id"], claimant_name="Fee")
        res = api.create_remediation_task(
            {"finding_id": finding["id"], "assigned_vendor_id": "vendor-1",
             "estimated_effort_hours": 2}, TEST_USERS["remediation_vendor_headers"])
        validate_error(res, "ERR_SITE_BLOCKED_BY_LEGAL")

    def test_accept_risk_blocked_when_site_blocked_by_legal(self, api, compliance_manager_headers):
        """PRD §3.7: "The accept-risk decision sits at the intersection of this section and §3.3.
        A ComplianceManager accepts the risk on a finding that is OPEN, moving it directly to the
        terminal WONT_FIX_ACCEPTED status; this is permitted only when the parent site is not
        BLOCKED (otherwise ERR_SITE_BLOCKED_BY_LEGAL)."

        Second AuditFinding->Site cross-entity test: with the site BLOCKED by a legal demand,
        accept-risk on its OPEN finding is rejected ERR_SITE_BLOCKED_BY_LEGAL.

        Design: Difficulty/cross_entity_state_dependency/remediation_blocked_when_site_blocked_by_legal
        """
        org, sub, site, scan = setup_completed_scan([finding_entry("1.4.3", "CRITICAL")],
                                                    audited_page_count=12)
        finding = list_findings_for_scan(scan["id"])[0]
        file_legal_demand(site["id"], claimant_name="Gee")
        res = api.accept_risk_finding(finding["id"], TEST_USERS["compliance_manager_headers"])
        validate_error(res, "ERR_SITE_BLOCKED_BY_LEGAL")

    def test_scan_start_blocked_when_subscription_suspended(self, api, audit_engineer_headers):
        """PRD §3.2: "Starting a scan advances it from QUEUED to RUNNING, but only if the parent
        site's subscription is in TRIAL or ACTIVE status; a subscription in any other status
        blocks the start with ERR_SUBSCRIPTION_NOT_ACTIVE."

        Subscription SUSPENDED -> starting a QUEUED scan on the site -> ERR_SUBSCRIPTION_NOT_ACTIVE.

        Design: Difficulty/cross_entity_state_dependency/scan_start_blocked_when_subscription_not_active
        """
        org, suspended, site = setup_subscription_suspended(tier="SCAN", audited_page_count=9)
        assert suspended["status"] == "SUSPENDED"
        scan = create_queued_scan(site["id"], wcag_target_level="A")
        res = api.start_scan(scan["id"], TEST_USERS["audit_engineer_headers"])
        validate_error(res, "ERR_SUBSCRIPTION_NOT_ACTIVE")

    def test_scan_start_allowed_when_subscription_active(self, api, audit_engineer_headers):
        """PRD §3.2: "Starting a scan advances it from QUEUED to RUNNING, but only if the parent
        site's subscription is in TRIAL or ACTIVE status; a subscription in any other status
        blocks the start with ERR_SUBSCRIPTION_NOT_ACTIVE."

        The permitted side of the same Scan->Subscription guard: with the subscription ACTIVE the
        QUEUED scan starts and reaches RUNNING.

        Design: Difficulty/cross_entity_state_dependency/scan_start_blocked_when_subscription_not_active
        """
        org, sub, site = setup_org_active_sub_site(tier="SCAN", audited_page_count=9)
        assert sub["status"] == "ACTIVE"
        scan = create_queued_scan(site["id"], wcag_target_level="A")
        started = validate_success(api.start_scan(scan["id"], TEST_USERS["audit_engineer_headers"]), 200)
        assert started["status"] == "RUNNING"


class TestResourceUniqueness:
    def test_duplicate_site_url_within_org_rejected(self, api, org_admin_headers):
        """PRD §3.1: "A site's url must be unique within its organization_id; a duplicate is
        rejected with ERR_DUPLICATE_SITE_URL."

        A second Site with an identical url under the same org -> ERR_DUPLICATE_SITE_URL.

        Design: Difficulty/resource_temporal_overlap/duplicate_site_url_within_org_rejected
        """
        org = create_org()
        owner = make_org_admin_headers(org["id"])
        validate_success(api.create_site(
            create_site_payload(org["id"], url="https://dup.test", audited_page_count=10), owner), 201)
        res = api.create_site(
            create_site_payload(org["id"], url="https://dup.test", audited_page_count=20), owner)
        validate_error(res, "ERR_DUPLICATE_SITE_URL")

    def test_same_url_allowed_under_different_org(self, api, org_admin_headers):
        """PRD §3.1: "A site's url must be unique within its organization_id; a duplicate is
        rejected with ERR_DUPLICATE_SITE_URL."

        Uniqueness is scoped per organization_id (point-equality within the org): the identical
        url registered under a different org succeeds, confirming the collision axis.

        Design: Difficulty/resource_temporal_overlap/duplicate_site_url_within_org_rejected
        """
        org_a = create_org()
        org_b = create_org()
        validate_success(api.create_site(
            create_site_payload(org_a["id"], url="https://shared.test", audited_page_count=10),
            make_org_admin_headers(org_a["id"])), 201)
        res = api.create_site(
            create_site_payload(org_b["id"], url="https://shared.test", audited_page_count=10),
            make_org_admin_headers(org_b["id"]))
        validate_success(res, 201)

    def test_second_subscription_per_org_rejected(self, api, org_admin_headers):
        """PRD §3.1: "Each organization may hold at most one Subscription. ... An attempt to
        create a second subscription for an organization that already has one is rejected with
        ERR_SUBSCRIPTION_EXISTS."

        A second Subscription for the same org -> ERR_SUBSCRIPTION_EXISTS.

        Design: Difficulty/resource_temporal_overlap/second_subscription_per_org_rejected
        """
        org, sub = create_org_with_trial_subscription(tier="SCAN")
        owner = make_org_admin_headers(org["id"])
        res = api.create_subscription(create_subscription_payload(org["id"], tier="MANAGED"), owner)
        validate_error(res, "ERR_SUBSCRIPTION_EXISTS")

    def test_subscription_allowed_for_org_without_one(self, api, org_admin_headers):
        """PRD §3.1: "Each organization may hold at most one Subscription. An OrgAdmin or
        PlatformAdmin creates a subscription by naming the organization_id and choosing a tier of
        SCAN, MONITOR, or MANAGED. A new subscription enters the TRIAL status."

        At-most-one capacity on the organization_id axis: a distinct org with no existing
        subscription accepts its first subscription (TRIAL), confirming the constraint is the
        second occupant, not the first.

        Design: Difficulty/resource_temporal_overlap/second_subscription_per_org_rejected
        """
        org = create_org()
        owner = make_org_admin_headers(org["id"])
        res = api.create_subscription(create_subscription_payload(org["id"], tier="SCAN"), owner)
        sub = validate_success(res, 201)
        assert sub["status"] == "TRIAL"


class TestBusinessViolations:
    def test_vpat_create_against_running_scan_rejected(self, api, compliance_manager_headers):
        """PRD §3.4: "the source scan must be COMPLETED, and a scan in any other status causes the
        create to be rejected with ERR_SCAN_NOT_COMPLETED."

        Creating a DRAFT VPAT against a RUNNING (not COMPLETED) scan -> ERR_SCAN_NOT_COMPLETED.

        Design: Corner/validations/vpat_create_scan_not_completed_returns_409
        """
        org, sub, site = setup_org_active_sub_site(tier="SCAN", audited_page_count=5)
        scan = create_running_scan(site["id"], wcag_target_level="A")
        res = api.create_vpat_report(
            {"site_id": site["id"], "source_scan_id": scan["id"]},
            TEST_USERS["compliance_manager_headers"])
        validate_error(res, "ERR_SCAN_NOT_COMPLETED")

    def test_training_complete_below_pass_rejected(self, api, org_admin_headers):
        """PRD §3.8: "Completion requires a score_pct (a number in the inclusive 0-to-100 range,
        required only at completion) of at least 80; a completion submitted with a score below 80
        is rejected with ERR_SCORE_BELOW_PASS".

        Completing training with score_pct=70 (<80) -> ERR_SCORE_BELOW_PASS.

        Design: Corner/validations/training_complete_below_pass_returns_422
        """
        org, enr = setup_training_in_progress()
        owner = make_org_admin_headers(org["id"])
        res = api.complete_training_enrollment(enr["id"], complete_training_payload(score_pct=70), owner)
        validate_error(res, "ERR_SCORE_BELOW_PASS")

    def test_certification_expire_before_deadline_rejected(self, api, platform_admin_headers):
        """PRD §3.5: "a PlatformAdmin may expire a certification, moving it from GRANTED to the
        terminal EXPIRED status, but only once the logical clock now is strictly past the
        certification's expires_at; an attempt to expire before that instant is rejected with
        ERR_NOT_YET_EXPIRED."

        GRANTED cert with expires_at one year out, clock still at default -> ERR_NOT_YET_EXPIRED.

        Design: Corner/validations/certification_expire_before_deadline_returns_409
        """
        org, site, scan, vpat, cert = setup_granted_certification()
        res = api.expire_certification(cert["id"], TEST_USERS["platform_admin_headers"])
        validate_error(res, "ERR_NOT_YET_EXPIRED")

    def test_retest_fk_mismatch_rejected(self, api, audit_engineer_headers):
        """PRD §2.8: "the canonical example is a retest run, whose referenced remediation task
        must belong to the same finding named in the body — that is, the task's finding_id must
        equal the retest's finding_id. An inconsistent set of foreign keys is rejected with
        ERR_FK_MISMATCH (HTTP 409)."

        A retest whose body finding_id != remediation_task_id.finding_id -> ERR_FK_MISMATCH.

        Design: Corner/validations/retest_fk_mismatch_returns_409
        """
        org, sub, site, scan = setup_completed_scan(
            [finding_entry("1.4.3", "CRITICAL"), finding_entry("2.1.1", "SERIOUS")])
        findings = list_findings_for_scan(scan["id"])
        f1, f2 = findings[0], findings[1]
        drive_task_to_submitted(f1["id"], vendor="v1")
        t2 = drive_task_to_submitted(f2["id"], vendor="v2")
        # Cross the ids: body finding_id = f1, task = t2 (which belongs to f2).
        res = api.create_retest_run(
            {"finding_id": f1["id"], "remediation_task_id": t2["id"], "outcome": "PASS"},
            TEST_USERS["audit_engineer_headers"])
        validate_error(res, "ERR_FK_MISMATCH")
