"""Remediation planning and audit engagements: the target-license guard at
plan creation and approval, referential-versus-temporal guard ordering, and
the remediation-versus-audit window comparison."""
from test_helpers import (
    ApiErrorId,
    SPEC_PROHIBITED_DISCOVERED,
    SPEC_RESTRICTED,
    TEST_USERS,
    api_client,
    complete_plan_payload,
    create_audit,
    create_patch_plan,
    create_remediation_plan_payload,
    finding_for_vulnerability,
    confirm_finding,
    get_success_data,
    list_approvals,
    manifest_component_spec,
    register_vulnerability,
    set_clock,
    setup_blocked_product,
    setup_product_with_completed_scan,
    setup_product_with_finding,
    validate_error,
    validate_success,
)

ENG_MGR = TEST_USERS["eng_manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def _component_id_by_purl(purl):
    components = get_success_data(
        api_client.list_components(ANALYST, params={"package_url": purl}))
    assert len(components) == 1, f"expected one catalogue component for {purl}"
    return components[0]


class TestPlanTargetLicenseGuard:
    def _finding_ctx(self, code, extra_spec):
        """Product with a CONFIRMED HIGH finding plus one extra manifest
        package (the prospective remediation target), already classified by
        the completed scan."""
        ctx = setup_product_with_completed_scan(
            product_overrides={"product_code": code},
            manifest=[manifest_component_spec(
                package_url="pkg:npm/vuln-lib@1.0.0",
                declared_license_spdx="MIT"), extra_spec])
        vuln = register_vulnerability(
            cve_id=f"CVE-2026-7{abs(hash(code)) % 9000 + 1000}",
            severity="HIGH", cvss_score=7.5,
            affected_package_url="pkg:npm/vuln-lib@1.0.0")
        finding = finding_for_vulnerability(ctx["product"]["id"], vuln["id"])
        ctx["finding"] = confirm_finding(ctx["product"]["id"], finding["id"])
        return ctx

    def test_strong_copyleft_target_rejected(self, api):
        """PRD §3.6: "the target component must reference an existing
        component with a compatible license — a `PROHIBITED` or otherwise
        incompatible target is refused with `ERR_INCOMPATIBLE_LICENSE`
        (HTTP 400)" at creation, and "for `UPGRADE` or `REPLACE` plans it
        requires the target component's license to be `PERMISSIVE` or
        `WEAK_COPYLEFT`" at approval. A STRONG_COPYLEFT target fails the
        guard wherever the guard is enforced.

        Design: Difficulty/cross_entity_state_dependency/remediation_plan_depends_on_component_license
        """
        ctx = self._finding_ctx(
            "XENT-2",
            manifest_component_spec(package_url="pkg:npm/gpl-target@2.0.0",
                                    declared_license_spdx="GPL-3.0"))
        target = _component_id_by_purl("pkg:npm/gpl-target@2.0.0")
        assert target["license_policy_classification"] == "STRONG_COPYLEFT"

        product_id = ctx["product"]["id"]
        create_resp = api.create_remediation_plan(
            product_id,
            create_remediation_plan_payload(
                ctx["finding"]["id"], plan_type="REPLACE",
                target_component_id=target["id"], target_version="2.0.0",
                migration_effort_days=3),
            ENG_MGR)
        if create_resp.status_code == 201:
            plan = validate_success(create_resp, 201)
            approve_resp = api.approve_remediation_plan(
                product_id, plan["id"], ENG_MGR)
            validate_error(approve_resp, ApiErrorId.ERR_INCOMPATIBLE_LICENSE, 400)
        else:
            validate_error(create_resp, ApiErrorId.ERR_INCOMPATIBLE_LICENSE, 400)

    def test_weak_copyleft_target_approves(self, api):
        """PRD §3.6: "for `UPGRADE` or `REPLACE` plans it requires the target
        component's license to be `PERMISSIVE` or `WEAK_COPYLEFT`. Approval
        moves the plan to `APPROVED`, computes
        `license_compatibility_verified`, and flips the linked finding's
        `remediation_status` to `IN_PROGRESS`."

        Design: Difficulty/cross_entity_state_dependency/remediation_plan_depends_on_component_license
        """
        ctx = self._finding_ctx(
            "XENT-2B",
            manifest_component_spec(package_url="pkg:npm/lgpl-target@1.0.0",
                                    declared_license_spdx="LGPL-2.1"))
        target = _component_id_by_purl("pkg:npm/lgpl-target@1.0.0")
        assert target["license_policy_classification"] == "WEAK_COPYLEFT"

        product_id = ctx["product"]["id"]
        plan = validate_success(api.create_remediation_plan(
            product_id,
            create_remediation_plan_payload(
                ctx["finding"]["id"], plan_type="REPLACE",
                target_component_id=target["id"], target_version="1.1.0",
                migration_effort_days=3),
            ENG_MGR), 201)
        assert plan["status"] == "PROPOSED"

        approved = validate_success(
            api.approve_remediation_plan(product_id, plan["id"], ENG_MGR))
        assert approved["status"] == "APPROVED"
        assert approved["license_compatibility_verified"] is True
        finding = get_success_data(api.get_vulnerability_finding(
            product_id, ctx["finding"]["id"], TEST_USERS["security_headers"]))
        assert finding["remediation_status"] == "IN_PROGRESS"


class TestReferentialBeatsTemporal:
    def test_prohibited_target_rejected_at_creation(self, api):
        """PRD §3.6: "Two business guards fire at creation: the target
        component must reference an existing component with a compatible
        license — a `PROHIBITED` or otherwise incompatible target is refused
        with `ERR_INCOMPATIBLE_LICENSE` (HTTP 400)".

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_conflict
        """
        ctx = setup_blocked_product(
            product_overrides={"product_code": "PRIO-2"},
            extra_specs=[manifest_component_spec(
                package_url="pkg:npm/vuln-lib@1.0.0",
                declared_license_spdx="MIT")])
        product_id = ctx["product"]["id"]
        target = _component_id_by_purl("pkg:npm/sneaky-lib@1.0.0")
        assert target["effective_classification"] == "PROHIBITED"

        vuln = register_vulnerability(
            cve_id="CVE-2026-70001", severity="HIGH", cvss_score=7.0,
            affected_package_url="pkg:npm/vuln-lib@1.0.0")
        finding = finding_for_vulnerability(product_id, vuln["id"])
        confirm_finding(product_id, finding["id"])

        resp = api.create_remediation_plan(
            product_id,
            create_remediation_plan_payload(
                finding["id"], plan_type="REPLACE",
                target_component_id=target["id"], migration_effort_days=3),
            ENG_MGR)
        validate_error(resp, ApiErrorId.ERR_INCOMPATIBLE_LICENSE, 400)

    def test_prohibited_target_rejected_even_with_expired_approval(self, api):
        """PRD §2.5: "a failure at any layer short-circuits all later layers"
        with "8. **Referential license compatibility** — a remediation plan's
        target component must exist and carry a compatible license, else
        `ERR_INCOMPATIBLE_LICENSE` (HTTP 400)" ahead of "9. **Approval
        temporal validity** — an approval request relied upon past its
        `expiry_at` fails with `ERR_APPROVAL_EXPIRED` (HTTP 409), enforced at
        release-gate evaluation and at BOM finalization." A plan-creation
        call carrying both an expired approval in the product's history and
        an incompatible target reports the referential failure. PRD §3.1:
        escalation to BLOCKED moves "every `PENDING` approval request ... to
        `EXPIRED`".

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_conflict
        """
        ctx = setup_product_with_completed_scan(
            product_overrides={"product_code": "PRIO-2B"},
            manifest=[SPEC_RESTRICTED, SPEC_PROHIBITED_DISCOVERED,
                      manifest_component_spec(
                          package_url="pkg:npm/vuln-lib@1.0.0",
                          declared_license_spdx="MIT")])
        product_id = ctx["product"]["id"]
        assert ctx["product"]["compliance_posture"] == "BLOCKED"
        approvals = list_approvals(product_id, ctx["analyst_headers"])
        assert len(approvals) == 1
        assert approvals[0]["status"] == "EXPIRED", (
            "the BLOCKED escalation expires every PENDING request (PRD §3.1)")

        target = _component_id_by_purl("pkg:npm/sneaky-lib@1.0.0")
        vuln = register_vulnerability(
            cve_id="CVE-2026-70002", severity="CRITICAL", cvss_score=9.0,
            affected_package_url="pkg:npm/vuln-lib@1.0.0")
        finding = finding_for_vulnerability(product_id, vuln["id"])
        confirm_finding(product_id, finding["id"])

        resp = api.create_remediation_plan(
            product_id,
            create_remediation_plan_payload(
                finding["id"], plan_type="REPLACE",
                target_component_id=target["id"], migration_effort_days=5),
            ENG_MGR)
        validate_error(resp, ApiErrorId.ERR_INCOMPATIBLE_LICENSE, 400)


class TestRemediationVsAuditWindow:
    def _plan_in_progress_with_audit(self, code, audit_target):
        ctx = setup_product_with_finding(
            severity="HIGH", package_url="pkg:npm/mit-lib@1.0.0",
            vuln_overrides={"cvss_score": 7.0},
            product_overrides={"product_code": code})
        product_id = ctx["product"]["id"]
        plan = create_patch_plan(product_id, ctx["finding"]["id"],
                                 migration_effort_days=3)
        get_success_data(api_client.approve_remediation_plan(product_id, plan["id"], ENG_MGR))
        get_success_data(api_client.start_remediation_plan(product_id, plan["id"], ENG_MGR))
        audit = create_audit(
            product_id, analyst=ctx["analyst_headers"],
            target_completion_at=audit_target)
        ctx["plan"] = plan
        ctx["audit"] = audit
        return ctx

    def test_remediation_completes_after_audit_target(self, api):
        """PRD §3.6: "Completion demands evidence: the manager supplies a
        `verification_scan_id` referencing a `COMPLETED` scan that shows the
        vulnerability absent, moving an `IN_PROGRESS` plan to `COMPLETED` —
        any other state is `ERR_PLAN_NOT_IN_PROGRESS` (HTTP 409) — stamping
        `actual_completion_at` at that moment and advancing the finding's
        `remediation_status` to `VERIFIED`". Completed at 2026-08-22 against
        an audit target of 2026-08-15, the remediation window overruns the
        audit window.

        Design: Difficulty/resource_temporal_overlap/audit_engagement_vs_remediation_window
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = self._plan_in_progress_with_audit("TEMP-2", "2026-08-15T00:00:00Z")
        product_id = ctx["product"]["id"]

        set_clock("2026-08-22T00:00:00Z")
        completed = validate_success(api.complete_remediation_plan(
            product_id, ctx["plan"]["id"],
            complete_plan_payload(ctx["scan"]["id"]), ENG_MGR))
        assert completed["status"] == "COMPLETED"
        assert completed["actual_completion_at"].startswith("2026-08-22")

        audit = get_success_data(api.get_audit_engagement(
            product_id, ctx["audit"]["id"], ctx["analyst_headers"]))
        assert audit["target_completion_at"].startswith("2026-08-15")
        assert (completed["actual_completion_at"][:10]
                > audit["target_completion_at"][:10]), (
            "remediation completed after the audit target date")

        finding = get_success_data(api.get_vulnerability_finding(
            product_id, ctx["finding"]["id"], TEST_USERS["security_headers"]))
        assert finding["remediation_status"] == "VERIFIED"

    def test_remediation_completes_before_audit_target(self, api):
        """PRD §3.6: "moving an `IN_PROGRESS` plan to `COMPLETED` — any other
        state is `ERR_PLAN_NOT_IN_PROGRESS` (HTTP 409) — stamping
        `actual_completion_at` at that moment and advancing the finding's
        `remediation_status` to `VERIFIED`". The same workflow completed at
        2026-08-10 lands inside the audit window whose target is 2026-08-15 —
        the comparison point of the overlapping windows reads in the opposite
        direction.

        Design: Difficulty/resource_temporal_overlap/audit_engagement_vs_remediation_window
        """
        set_clock("2026-08-01T00:00:00Z")
        ctx = self._plan_in_progress_with_audit("TEMP-2B",
                                                "2026-08-15T00:00:00Z")
        product_id = ctx["product"]["id"]

        set_clock("2026-08-10T00:00:00Z")
        completed = validate_success(api.complete_remediation_plan(
            product_id, ctx["plan"]["id"],
            complete_plan_payload(ctx["scan"]["id"]), ENG_MGR))
        assert completed["status"] == "COMPLETED"
        assert completed["actual_completion_at"].startswith("2026-08-10")

        audit = get_success_data(api.get_audit_engagement(
            product_id, ctx["audit"]["id"], ctx["analyst_headers"]))
        assert audit["target_completion_at"].startswith("2026-08-15")
        assert (completed["actual_completion_at"][:10]
                < audit["target_completion_at"][:10])

        finding = get_success_data(api.get_vulnerability_finding(
            product_id, ctx["finding"]["id"], TEST_USERS["security_headers"]))
        assert finding["remediation_status"] == "VERIFIED"


class TestPlanRbac:
    def test_analyst_cannot_approve_plan(self, api):
        """PRD §4: approving a remediation plan is the EngineeringManager's
        operation; PRD §2.1: "an authenticated user attempting an operation
        outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/validations/auth_insufficient_permissions_returns_error
        """
        ctx = setup_product_with_finding(
            severity="HIGH", package_url="pkg:npm/mit-lib@1.0.0",
            product_overrides={"product_code": "RBAC-TEST"})
        plan = create_patch_plan(ctx["product"]["id"], ctx["finding"]["id"])
        resp = api.approve_remediation_plan(
            ctx["product"]["id"], plan["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)
