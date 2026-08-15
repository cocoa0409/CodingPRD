"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_audit_engagement_payload,
    create_component_payload,
    create_dependency_scan_payload,
    create_product_payload,
    create_release_gate_payload,
    create_remediation_plan_payload,
    create_vulnerability_payload,
    engineering_decision_payload,
    fulfill_ticket_payload,
    legal_decision_payload,
    manifest_component_spec,
    verify_remediation_payload,
)
from .test_users import (
    TEST_USERS,
    make_analyst_headers,
)

ANALYST = TEST_USERS["analyst_headers"]
LEGAL = TEST_USERS["legal_headers"]
ENG_MGR = TEST_USERS["eng_manager_headers"]
SECURITY = TEST_USERS["security_headers"]
RELEASE_MGR = TEST_USERS["release_manager_headers"]
CISO = TEST_USERS["ciso_headers"]
ADMIN = TEST_USERS["admin_headers"]

# Canonical manifest lines used across fixtures. Each names a package the scan
# resolves against the catalogue (PRD §3.3).
SPEC_MIT = manifest_component_spec(
    package_url="pkg:npm/mit-lib@1.0.0", declared_license_spdx="MIT")
SPEC_LGPL = manifest_component_spec(
    package_url="pkg:npm/lgpl-lib@1.0.0", declared_license_spdx="LGPL-2.1")
SPEC_GPL = manifest_component_spec(
    package_url="pkg:npm/gpl-lib@2.0.0", declared_license_spdx="GPL-3.0")
SPEC_RESTRICTED = manifest_component_spec(
    package_url="pkg:npm/restricted-lib@1.0.0",
    declared_license_spdx="CC-BY-NC-4.0")
# A package that declares a permissive license in its metadata but is
# discovered to carry WTFPL when the scanner inspects it: declared classification
# passes the submission's prohibited-content screen, and scan-time discovery
# drives the PROHIBITED classification (PRD §3.2, §3.3).
SPEC_PROHIBITED_DISCOVERED = manifest_component_spec(
    package_url="pkg:npm/sneaky-lib@1.0.0",
    declared_license_spdx="MIT",
    discovered_license_spdx="WTFPL")


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server-side logical clock (PRD §2.9)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: single-entity creation ───────────────────

def create_product(distribution_model="SaaS", analyst=None, **overrides):
    return get_success_data(api_client.create_product(
        create_product_payload(distribution_model=distribution_model, **overrides),
        analyst or ANALYST))


def get_product(product_id, headers=None):
    return get_success_data(api_client.get_product(product_id, headers or ANALYST))


def create_component(**overrides):
    return get_success_data(
        api_client.create_component(create_component_payload(**overrides), ANALYST))


def create_scan(product_id, manifest, analyst=None, **overrides):
    """Create a DependencyScan, OCC-guarded on the product's current
    posture_version (PRD §2.8). The product is re-read first so the expected
    version is never stale from fixture-internal mutations."""
    actor = analyst or ANALYST
    product = get_product(product_id, actor)
    return get_success_data(api_client.create_dependency_scan(
        product_id,
        create_dependency_scan_payload(
            product["posture_version"], manifest=manifest, **overrides),
        actor))


def process_scan(scan_id):
    """Drive a QUEUED scan synchronously through every stage with all cascaded
    side effects applied (PRD §3.3)."""
    return get_success_data(api_client.process_next_scan(scan_id, ADMIN))


def register_vulnerability(security=None, **overrides):
    return get_success_data(api_client.create_vulnerability(
        create_vulnerability_payload(**overrides), security or SECURITY))


# ─── Tier 2: product + completed scan + BOM ───────────

def get_bom(product_id, bom_id, headers=None):
    return get_success_data(
        api_client.get_bom(product_id, bom_id, headers or ANALYST))


def list_bom_entries(product_id, bom_id, headers=None):
    return get_success_data(api_client.list_bom_entries(
        product_id, bom_id, headers or ANALYST, params={"limit": 100}))


def list_boms(product_id, headers=None):
    return get_success_data(
        api_client.list_boms(product_id, headers or ANALYST, params={"limit": 100}))


def setup_product_with_completed_scan(distribution_model="SaaS",
                                      manifest=None, analyst_id="analyst-1",
                                      product_overrides=None):
    """Product + a completed dependency scan whose referenced manifest resolves
    into a FINALIZED bill of materials (PRD §3.3). Returns a dict with the
    product (re-read after the cascade), scan, bom, and bom entries."""
    actor = make_analyst_headers(analyst_id)
    product = create_product(distribution_model, analyst=actor,
                             **(product_overrides or {}))
    specs = manifest if manifest is not None else [SPEC_MIT]
    scan = create_scan(product["id"], specs, analyst=actor)
    scan = process_scan(scan["id"])
    boms = list_boms(product["id"], actor)
    assert len(boms) == 1, f"expected exactly one BOM after scan, got {len(boms)}"
    bom = boms[0]
    entries = list_bom_entries(product["id"], bom["id"], actor)
    product = get_product(product["id"], actor)
    return {"product": product, "scan": scan, "bom": bom, "entries": entries,
            "analyst_headers": actor}


def setup_blocked_product(distribution_model="SaaS", analyst_id="analyst-1",
                          extra_specs=None, product_overrides=None):
    """Product whose active BOM contains a PROHIBITED-classified entry: the
    manifest line declares MIT but the scan discovers WTFPL, so the submission
    passes the prohibited-content screen and the discovered classification
    drives the product to BLOCKED at scan completion (PRD §3.2, §3.3)."""
    specs = [SPEC_PROHIBITED_DISCOVERED] + list(extra_specs or [])
    ctx = setup_product_with_completed_scan(
        distribution_model, manifest=specs, analyst_id=analyst_id,
        product_overrides=product_overrides)
    assert ctx["product"]["compliance_posture"] == "BLOCKED", (
        f"setup failed: product not BLOCKED, got "
        f"{ctx['product']['compliance_posture']!r}")
    return ctx


# ─── Tier 2: vulnerability findings ───────────────────

def list_findings(product_id, headers=None):
    return get_success_data(api_client.list_vulnerability_findings(
        product_id, headers or SECURITY, params={"limit": 100}))


def finding_for_vulnerability(product_id, vulnerability_id, headers=None):
    """The single finding created for a registered vulnerability on this
    product (PRD §3.5: a finding is created for every BOM entry that ships the
    affected component)."""
    findings = [f for f in list_findings(product_id, headers)
                if f["vulnerability_id"] == vulnerability_id]
    assert len(findings) == 1, (
        f"expected exactly one finding for vulnerability {vulnerability_id}, "
        f"got {len(findings)}")
    return findings[0]


def confirm_finding(product_id, finding_id, headers=None):
    return get_success_data(
        api_client.confirm_finding(product_id, finding_id, headers or SECURITY))


def setup_product_with_finding(severity="HIGH",
                               package_url="pkg:npm/mit-lib@1.0.0",
                               confirm=True, distribution_model="SaaS",
                               vuln_overrides=None, product_overrides=None):
    """Product with a completed scan (manifest ships `package_url`) plus one
    registered vulnerability affecting that package; returns the context with
    the finding (CONFIRMED by default)."""
    ctx = setup_product_with_completed_scan(
        distribution_model,
        manifest=[manifest_component_spec(package_url=package_url)],
        product_overrides=product_overrides)
    vuln = register_vulnerability(
        cve_id=f"CVE-2026-{abs(hash(package_url)) % 90000 + 10000}",
        severity=severity,
        affected_package_url=package_url,
        **(vuln_overrides or {}))
    finding = finding_for_vulnerability(ctx["product"]["id"], vuln["id"])
    if confirm:
        finding = confirm_finding(ctx["product"]["id"], finding["id"])
    ctx.update({"vulnerability": vuln, "finding": finding})
    return ctx


# ─── Tier 3: remediation plan lifecycle ───────────────

def create_patch_plan(product_id, finding_id, eng=None, **overrides):
    return get_success_data(api_client.create_remediation_plan(
        product_id,
        create_remediation_plan_payload(finding_id, **overrides),
        eng or ENG_MGR))


def walk_plan_to_completed(product_id, plan_id, verification_scan_id, eng=None):
    """Approve → start → complete a remediation plan. Completion stamps
    `actual_completion_at` and advances the linked finding's
    `remediation_status` to VERIFIED (PRD §3.6)."""
    actor = eng or ENG_MGR
    get_success_data(api_client.approve_remediation_plan(product_id, plan_id, actor))
    get_success_data(api_client.start_remediation_plan(product_id, plan_id, actor))
    return get_success_data(api_client.complete_remediation_plan(
        product_id, plan_id, {"verification_scan_id": verification_scan_id}, actor))


def verify_finding_via_remediation(product_id, finding_id, scan_id):
    """Drive a finding to REMEDIATED: a PATCH remediation plan is walked to
    COMPLETED (which sets the finding's remediation_status to VERIFIED), then
    the analyst verifies the remediation (PRD §3.5, §3.6). Returns the
    REMEDIATED finding."""
    plan = create_patch_plan(product_id, finding_id)
    walk_plan_to_completed(product_id, plan["id"], scan_id)
    return get_success_data(api_client.verify_remediation(
        product_id, finding_id, verify_remediation_payload(), SECURITY))


# ─── Tier 3: license approval workflow ────────────────

def list_approvals(product_id, headers=None):
    return get_success_data(api_client.list_license_approvals(
        product_id, headers or ANALYST, params={"limit": 100}))


def setup_product_with_approval_request(distribution_model="SaaS",
                                        analyst_id="analyst-1",
                                        product_overrides=None):
    """Product whose completed scan surfaced a RESTRICTED entry, spawning a
    license approval request in PENDING (PRD §3.3). Returns ctx with the
    approval request."""
    ctx = setup_product_with_completed_scan(
        distribution_model, manifest=[SPEC_RESTRICTED], analyst_id=analyst_id,
        product_overrides=product_overrides)
    approvals = list_approvals(ctx["product"]["id"], ctx["analyst_headers"])
    assert len(approvals) == 1, (
        f"expected exactly one approval request, got {len(approvals)}")
    ctx["approval"] = approvals[0]
    return ctx


def approve_license_request(product_id, request_id):
    """Walk a PENDING request through legal APPROVE and engineering APPROVE to
    APPROVED (PRD §3.4). Returns the APPROVED request."""
    get_success_data(api_client.assign_legal(product_id, request_id, LEGAL))
    get_success_data(api_client.legal_decision(
        product_id, request_id, legal_decision_payload("APPROVE"), LEGAL))
    return get_success_data(api_client.engineering_decision(
        product_id, request_id, engineering_decision_payload("APPROVE"), ENG_MGR))


# ─── Tier 4: obligation tickets, notice, gates ────────

def list_tickets(product_id, headers=None):
    return get_success_data(api_client.list_obligation_tickets(
        product_id, headers or ANALYST, params={"limit": 100}))


def fulfill_all_obligation_tickets(product_id, analyst=None, leave_unresolved=0):
    """Start + fulfill obligation tickets on the product, so the BOM's
    obligations_fulfilled_pct reflects fulfilled-plus-waived over the total
    (PRD §3.4, §3.7). With `leave_unresolved`, the last N tickets are left
    OPEN (boundary tests control the exact percentage this way)."""
    actor = analyst or ANALYST
    fulfilled = []
    tickets = [t for t in list_tickets(product_id, actor)
               if t["status"] not in ("FULFILLED", "WAIVED")]
    if leave_unresolved:
        tickets = tickets[:-leave_unresolved]
    for ticket in tickets:
        if ticket["status"] == "OPEN":
            get_success_data(
                api_client.start_ticket(product_id, ticket["id"], actor))
        fulfilled.append(get_success_data(api_client.fulfill_ticket(
            product_id, ticket["id"], fulfill_ticket_payload(), actor)))
    return fulfilled


def generate_notice(product_id, bom_id, analyst=None):
    return get_success_data(
        api_client.generate_notice(product_id, bom_id, analyst or ANALYST))


def create_gate(product_id, bom_id, release_version="1.0.0", headers=None):
    return get_success_data(api_client.create_release_gate(
        product_id,
        create_release_gate_payload(bom_id, release_version=release_version),
        headers or RELEASE_MGR))


def evaluate_gate(product_id, gate_id, headers=None):
    """Evaluate a gate, OCC-guarded on the BOM's current version (PRD §2.8).
    The BOM is re-read first so notice generation or recomputation cannot
    leave the expected version stale."""
    actor = headers or RELEASE_MGR
    gate = get_success_data(api_client.get_release_gate(product_id, gate_id, actor))
    bom = get_bom(product_id, gate["bom_id"], actor)
    return api_client.evaluate_release_gate(
        product_id, gate_id, {"expected_bom_version": bom["version"]}, actor)


def setup_gate_ready(distribution_model="SaaS", manifest=None,
                     fulfill_tickets=True, analyst_id="analyst-1",
                     product_overrides=None):
    """Product + FINALIZED BOM (+ all obligation tickets fulfilled) + NOTICE
    file generated + an OPEN release gate. Returns ctx(product, scan, bom,
    entries, gate)."""
    ctx = setup_product_with_completed_scan(
        distribution_model, manifest=manifest, analyst_id=analyst_id,
        product_overrides=product_overrides)
    product_id = ctx["product"]["id"]
    if fulfill_tickets:
        fulfill_all_obligation_tickets(product_id, ctx["analyst_headers"])
    generate_notice(product_id, ctx["bom"]["id"], ctx["analyst_headers"])
    ctx["bom"] = get_bom(product_id, ctx["bom"]["id"])
    ctx["gate"] = create_gate(product_id, ctx["bom"]["id"])
    return ctx


# ─── Tier 4: audit engagements ────────────────────────

def create_audit(product_id, analyst=None, **overrides):
    return get_success_data(api_client.create_audit_engagement(
        product_id, create_audit_engagement_payload(**overrides),
        analyst or ANALYST))
