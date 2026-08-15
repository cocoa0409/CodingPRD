"""Authentication, authorization, optimistic concurrency, and the validation
pipeline's ordering of posture checks ahead of prohibited-content checks."""
from test_helpers import (
    ApiErrorId,
    SPEC_MIT,
    SPEC_PROHIBITED_DISCOVERED,
    TEST_USERS,
    create_dependency_scan_payload,
    create_patch_plan,
    create_product,
    create_product_payload,
    create_scan,
    get_product,
    get_success_data,
    legal_decision_payload,
    manifest_component_spec,
    process_scan,
    setup_blocked_product,
    setup_product_with_approval_request,
    setup_product_with_finding,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
LEGAL = TEST_USERS["legal_headers"]
SECURITY = TEST_USERS["security_headers"]
ENG_MGR = TEST_USERS["eng_manager_headers"]

# A manifest line whose declared license is on the PROHIBITED list
# (PRD §3.2: "WTFPL, unlicensed code, proprietary licenses without any grant,
# and SSPL-1.0 in a SaaS context classify as `PROHIBITED`").
SPEC_WTFPL_DECLARED = manifest_component_spec(
    package_url="pkg:npm/wtfpl-lib@1.0.0", declared_license_spdx="WTFPL")


class TestAuthentication:
    def test_missing_user_context_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two authentication headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring
        the capacity in which they act. A request missing either header, or
        carrying an unrecognized role, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/auth_missing_header_returns_error
        """
        resp = api.list_products({"Content-Type": "application/json"})
        validate_error(
            resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestRoleEnforcement:
    def test_legal_counsel_cannot_create_product(self, api, legal_headers):
        """PRD §4: product creation is the ComplianceAnalyst's operation;
        PRD §2.1: "an authenticated user attempting an operation outside their
        role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/roles/legal_counsel_cannot_create_product
        """
        resp = api.create_product(
            create_product_payload(product_code="RBAC-DENY"), legal_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)

    def test_security_analyst_cannot_record_legal_decision(self, api):
        """PRD §4: recording the legal decision is the LegalCounsel's
        operation; PRD §2.1: "an authenticated user attempting an operation
        outside their role is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."

        Design: Corner/roles/security_analyst_cannot_approve_license
        """
        ctx = setup_product_with_approval_request(
            product_overrides={"product_code": "RBAC-LEGAL"})
        product_id = ctx["product"]["id"]
        request_id = ctx["approval"]["id"]
        get_success_data(api.assign_legal(product_id, request_id, LEGAL))

        resp = api.legal_decision(
            product_id, request_id, legal_decision_payload("APPROVE"), SECURITY)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, 403)


class TestProhibitedContentScreen:
    def test_prohibited_manifest_rejected(self, api):
        """PRD §3.3: "A submission whose referenced manifest contains
        prohibited components is refused with `ERR_PROHIBITED_COMPONENT`
        (HTTP 403) unless a CISO waiver covers it." WTFPL is on the PROHIBITED
        list of §3.2.

        Design: Corner/errors/error_prohibited_component_triggerable
        """
        product = create_product(product_code="ERR-PROHIB")
        resp = api.create_dependency_scan(
            product["id"],
            create_dependency_scan_payload(
                product["posture_version"], manifest=[SPEC_WTFPL_DECLARED]),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_PROHIBITED_COMPONENT, 403)


class TestOptimisticConcurrency:
    def test_stale_product_version_rejected(self, api):
        """PRD §2.8: "If `expected_product_version` does not match the
        product's current `posture_version`, the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and no scan is created."

        Design: Corner/errors/error_stale_version_triggerable
        """
        product = create_product(product_code="STALE")
        create_scan(product["id"], [SPEC_MIT])  # advances posture_version

        fresh = get_product(product["id"])
        assert fresh["posture_version"] == product["posture_version"] + 1
        resp = api.create_dependency_scan(
            product["id"],
            create_dependency_scan_payload(
                product["posture_version"], manifest=[SPEC_MIT]),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    def test_posture_version_monotonic_through_cancel(self, api):
        """PRD §3.1: "A new product starts with `compliance_posture` set to
        `COMPLIANT`, `posture_version` at 1". PRD §3.3: "the product's
        `posture_version` is incremented at creation". PRD §2.4: "`version` —
        a system-managed integer that increments with every modification" —
        cancellation modifies the scan, not the product, so the product's
        posture_version never falls back.

        Design: Difficulty/compensating_invariant/product_version_consistency_through_cascades
        """
        product = create_product(product_code="INV-1")
        assert product["posture_version"] == 1

        scan = create_scan(product["id"], [SPEC_MIT])
        after_create = get_product(product["id"])
        assert after_create["posture_version"] == 2, (
            f"scan creation increments posture_version, got "
            f"{after_create['posture_version']}")

        cancelled = validate_success(api.cancel_dependency_scan(
            product["id"], scan["id"], ANALYST))
        assert cancelled["status"] == "CANCELLED"
        after_cancel = get_product(product["id"])
        assert after_cancel["posture_version"] == 2, (
            f"cancellation must not decrement posture_version, got "
            f"{after_cancel['posture_version']}")

    def test_posture_version_advances_and_stale_write_rejected(self, api):
        """PRD §2.8: "Creating a dependency scan requires the request body to
        carry `expected_product_version`, the client's last-observed
        `posture_version` of the target product. Scan creation itself advances
        the product's `posture_version`, so a second writer working from a
        stale read would otherwise silently interleave its work with state it
        never saw."

        Design: Difficulty/compensating_invariant/product_version_consistency_through_cascades
        """
        product = create_product(product_code="INV-1B")
        create_scan(product["id"], [SPEC_MIT])

        # A writer holding the pre-scan version is rejected...
        resp = api.create_dependency_scan(
            product["id"],
            create_dependency_scan_payload(
                product["posture_version"], manifest=[SPEC_MIT]),
            ANALYST)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        # ...while a writer carrying the current version proceeds.
        scan2 = create_scan(product["id"], [SPEC_MIT])
        assert scan2["status"] == "QUEUED"
        assert get_product(product["id"])["posture_version"] == 3


class TestPostureBeforeProhibitedContent:
    def test_blocked_product_wins_over_prohibited_manifest(self, api):
        """PRD §2.5: "Incoming requests are validated against an ordered
        pipeline; a failure at any layer short-circuits all later layers, so
        the error a client receives always reflects the earliest failing
        check." Layer "4. **Product posture** — operations that require a
        non-blocked product (creating dependency scans, creating release
        gates, approving remediation plans) fail with `ERR_PRODUCT_BLOCKED`
        (HTTP 409) while the product's posture is `BLOCKED`" precedes layer
        "6. **Prohibited-content safety** — a scan submission whose manifest
        contains prohibited components is refused with
        `ERR_PROHIBITED_COMPONENT` (HTTP 403) absent a CISO waiver."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_conflict
        """
        ctx = setup_blocked_product(
            product_overrides={"product_code": "PRIO-1"})
        product_id = ctx["product"]["id"]
        assert ctx["product"]["compliance_posture"] == "BLOCKED"

        fresh = get_product(product_id)
        resp = api.create_dependency_scan(
            product_id,
            create_dependency_scan_payload(
                fresh["posture_version"], manifest=[SPEC_WTFPL_DECLARED]),
            ctx["analyst_headers"])
        validate_error(resp, ApiErrorId.ERR_PRODUCT_BLOCKED, 409)

    def test_blocked_product_wins_over_plan_approval(self, api):
        """PRD §3.1: "A `BLOCKED` product refuses new dependency scans, new
        release gates, and remediation-plan approvals with
        `ERR_PRODUCT_BLOCKED` (HTTP 409)." The posture layer (§2.5 layer 4)
        fires on the approval attempt regardless of the plan's own state.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_conflict
        """
        ctx = setup_product_with_finding(
            severity="HIGH", package_url="pkg:npm/mit-lib@1.0.0",
            product_overrides={"product_code": "PRIO-1B"})
        product_id = ctx["product"]["id"]
        plan = create_patch_plan(product_id, ctx["finding"]["id"])

        # Escalate: a second scan whose discovered WTFPL drives the product
        # to BLOCKED (PRD §3.3).
        scan2 = create_scan(product_id, [SPEC_PROHIBITED_DISCOVERED],
                            analyst=ctx["analyst_headers"])
        process_scan(scan2["id"])
        assert get_product(product_id)["compliance_posture"] == "BLOCKED"

        resp = api.approve_remediation_plan(product_id, plan["id"], ENG_MGR)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_BLOCKED, 409)
