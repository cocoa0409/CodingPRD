"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so that a broken setup surfaces as a
clear "Setup failed" error rather than a confusing assertion failure deep inside a test.

The test harness restarts the API server and wipes the database before EVERY test, so every
fixture builds its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_organization_payload, create_subscription_payload, create_site_payload,
    activate_subscription_payload, create_scan_payload, complete_scan_payload, finding_entry,
    create_remediation_task_payload, create_retest_run_payload, create_vpat_report_payload,
    issue_vpat_payload, create_legal_demand_payload, create_certification_payload,
    create_training_enrollment_payload, set_clock_payload, unique_url,
)
from .test_users import TEST_USERS, make_org_admin_headers


# ─── Clock control ────────────────────────────────────────────────────────
def set_clock(to_iso8601: str):
    """Set the logical clock to a given ISO 8601 UTC instant."""
    return get_success_data(api_client.set_clock(
        set_clock_payload(to_iso8601), TEST_USERS["platform_admin_headers"]))


def read_clock():
    return get_success_data(api_client.get_clock(TEST_USERS["platform_admin_headers"]))


# ─── Tier 1/2: Base hierarchy (org → subscription → site) ───────────────────
def create_org():
    """Create an Organization. Returns the org dict."""
    return get_success_data(api_client.create_organization(
        create_organization_payload(), TEST_USERS["platform_admin_headers"]))


def create_org_with_trial_subscription(tier="MONITOR"):
    """Org + a TRIAL subscription. Returns (org, subscription)."""
    org = create_org()
    owner = make_org_admin_headers(org["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(org["id"], tier=tier), owner))
    return org, sub


def setup_org_active_sub_site(tier="MONITOR", audited_page_count=10, site_url=None):
    """Org + ACTIVE subscription + one Site. Returns (org, subscription, site).

    Subscription is created TRIAL then activated (TRIAL->ACTIVE) with its fresh version.
    Site is registered before activation so the invoice covers it.
    """
    org = create_org()
    owner = make_org_admin_headers(org["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(org["id"], tier=tier), owner))
    site = get_success_data(api_client.create_site(
        create_site_payload(org["id"], url=site_url, audited_page_count=audited_page_count), owner))
    activated = get_success_data(api_client.activate_subscription(
        sub["id"], activate_subscription_payload(sub["version"]), owner))
    return org, activated, site


def add_site(org_id, audited_page_count=10, url=None):
    """Register one more Site under an existing org. Returns the site dict."""
    owner = make_org_admin_headers(org_id)
    return get_success_data(api_client.create_site(
        create_site_payload(org_id, url=url, audited_page_count=audited_page_count), owner))


def setup_org_with_n_sites(page_counts, tier="MONITOR"):
    """Org + a TRIAL subscription + len(page_counts) sites with the given page counts.
    Returns (org, subscription, [sites]). Used for invoice round-per-site tests."""
    org = create_org()
    owner = make_org_admin_headers(org["id"])
    sub = get_success_data(api_client.create_subscription(
        create_subscription_payload(org["id"], tier=tier), owner))
    sites = []
    for pc in page_counts:
        site = get_success_data(api_client.create_site(
            create_site_payload(org["id"], url=unique_url(), audited_page_count=pc), owner))
        sites.append(site)
    return org, sub, sites


# ─── Tier 3: Scan lifecycle ─────────────────────────────────────────────────
def create_queued_scan(site_id, wcag_target_level="AA"):
    """Queue a scan on a site. Returns the QUEUED scan dict."""
    return get_success_data(api_client.create_scan(
        create_scan_payload(site_id, wcag_target_level), TEST_USERS["audit_engineer_headers"]))


def create_running_scan(site_id, wcag_target_level="AA"):
    """Queue + start a scan. Returns the RUNNING scan dict."""
    scan = create_queued_scan(site_id, wcag_target_level)
    return get_success_data(api_client.start_scan(
        scan["id"], TEST_USERS["audit_engineer_headers"]))


def complete_scan_with_findings(scan_id, findings):
    """Complete a RUNNING scan, emitting the given findings[] entries.
    Returns the COMPLETED scan dict."""
    return get_success_data(api_client.complete_scan(
        scan_id, complete_scan_payload(findings=findings), TEST_USERS["audit_engineer_headers"]))


def setup_completed_scan(findings, tier="MONITOR", audited_page_count=10):
    """Org + ACTIVE sub + Site + a COMPLETED scan emitting `findings`.
    Returns (org, sub, site, scan)."""
    org, sub, site = setup_org_active_sub_site(tier=tier, audited_page_count=audited_page_count)
    scan = create_running_scan(site["id"])
    completed = complete_scan_with_findings(scan["id"], findings)
    return org, sub, site, completed


def list_findings_for_scan(scan_id):
    """Return the list of findings emitted by a scan, in creation order."""
    data, _meta = _paginated(api_client.list_findings(
        TEST_USERS["audit_engineer_headers"], params={"scan_id": scan_id, "limit": 100}))
    return data


def _paginated(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


# ─── Tier 3: Remediation loop ───────────────────────────────────────────────
def create_task(finding_id, supersedes_task_id=None, vendor="vendor-1", effort=2):
    """Create a remediation task on a finding (OPEN->IN_REMEDIATION, or REOPENED->IN_REMEDIATION
    when supersedes_task_id set). Returns the task dict."""
    return get_success_data(api_client.create_remediation_task(
        create_remediation_task_payload(
            finding_id, assigned_vendor_id=vendor, estimated_effort_hours=effort,
            supersedes_task_id=supersedes_task_id),
        TEST_USERS["remediation_vendor_headers"]))


def drive_task_to_submitted(finding_id, supersedes_task_id=None, vendor="vendor-1", effort=2):
    """Create task on finding -> begin -> submit. Finding ends RETEST_PENDING; task SUBMITTED.
    Returns the task dict (after submit)."""
    task = create_task(finding_id, supersedes_task_id=supersedes_task_id, vendor=vendor, effort=effort)
    get_success_data(api_client.begin_remediation_task(
        task["id"], TEST_USERS["remediation_vendor_headers"]))
    return get_success_data(api_client.submit_remediation_task(
        task["id"], TEST_USERS["remediation_vendor_headers"]))


def record_retest(finding_id, remediation_task_id, outcome):
    """Record a retest run. Returns the retest dict."""
    return get_success_data(api_client.create_retest_run(
        create_retest_run_payload(finding_id, remediation_task_id, outcome),
        TEST_USERS["audit_engineer_headers"]))


def resolve_finding(finding_id, vendor="vendor-1", effort=2):
    """Drive a finding OPEN -> IN_REMEDIATION -> RETEST_PENDING -> RESOLVED (PASS retest).
    Returns the accepted task dict."""
    task = drive_task_to_submitted(finding_id, vendor=vendor, effort=effort)
    record_retest(finding_id, task["id"], "PASS")
    return task


def reopen_finding(finding_id, vendor="vendor-1", effort=2):
    """Drive a finding OPEN -> ... -> RETEST_PENDING -> REOPENED (FAIL retest).
    Returns the rejected task dict."""
    task = drive_task_to_submitted(finding_id, vendor=vendor, effort=effort)
    record_retest(finding_id, task["id"], "FAIL")
    return task


# ─── Tier 3/5: VPAT + certification lifecycle ───────────────────────────────
def create_draft_vpat(site_id, source_scan_id):
    """Create a DRAFT VpatReport pinned to a COMPLETED scan. Returns the report dict."""
    return get_success_data(api_client.create_vpat_report(
        create_vpat_report_payload(site_id, source_scan_id),
        TEST_USERS["compliance_manager_headers"]))


def scan_version(scan_id):
    """Read the live version of a scan."""
    return get_success_data(api_client.get_scan(
        scan_id, TEST_USERS["compliance_manager_headers"]))["version"]


def issue_vpat(vpat_id, source_scan_id):
    """Issue a DRAFT VPAT using the live source scan version as expected_scan_version.
    Returns the ISSUED report dict."""
    sv = scan_version(source_scan_id)
    return get_success_data(api_client.issue_vpat_report(
        vpat_id, issue_vpat_payload(sv), TEST_USERS["compliance_manager_headers"]))


def grant_certification(site_id, vpat_report_id):
    """Grant a certification backed by an ISSUED VPAT. Returns the certification dict."""
    return get_success_data(api_client.create_certification(
        create_certification_payload(site_id, vpat_report_id),
        TEST_USERS["compliance_manager_headers"]))


def setup_issued_vpat_single_critical_resolved(tier="MANAGED", audited_page_count=15):
    """Full chain: org + ACTIVE sub + site + COMPLETED scan (1 CRITICAL) -> finding RESOLVED ->
    DRAFT VPAT -> ISSUED VPAT. Returns (org, site, scan, vpat)."""
    org, sub, site, scan = setup_completed_scan(
        [finding_entry("1.4.3", "CRITICAL")], tier=tier, audited_page_count=audited_page_count)
    finding = list_findings_for_scan(scan["id"])[0]
    resolve_finding(finding["id"])
    vpat = create_draft_vpat(site["id"], scan["id"])
    issued = issue_vpat(vpat["id"], scan["id"])
    return org, site, scan, issued


def setup_granted_certification(tier="MANAGED", audited_page_count=15):
    """Full chain through a GRANTED certification. Returns (org, site, scan, vpat, certification)."""
    org, site, scan, vpat = setup_issued_vpat_single_critical_resolved(
        tier=tier, audited_page_count=audited_page_count)
    cert = grant_certification(site["id"], vpat["id"])
    return org, site, scan, vpat, cert


# ─── Legal demand lifecycle ─────────────────────────────────────────────────
def file_legal_demand(site_id, claimant_name="Doe", response_due_at="2026-04-01T00:00:00Z"):
    """Record a LegalDemand against a site (enters RECEIVED, blocks the site).
    Returns the demand dict."""
    return get_success_data(api_client.create_legal_demand(
        create_legal_demand_payload(site_id, claimant_name, response_due_at),
        TEST_USERS["compliance_manager_headers"]))


def respond_legal_demand(ld_id):
    return get_success_data(api_client.respond_legal_demand(
        ld_id, TEST_USERS["compliance_manager_headers"]))


def resolve_legal_demand(ld_id):
    return get_success_data(api_client.resolve_legal_demand(
        ld_id, TEST_USERS["compliance_manager_headers"]))


# ─── Subscription lifecycle helpers ─────────────────────────────────────────
def setup_subscription_past_due(tier="SCAN", audited_page_count=5):
    """Org + Site + subscription driven TRIAL->ACTIVE->PAST_DUE.
    Returns (org, subscription_after_past_due, site)."""
    org, sub, site = setup_org_active_sub_site(tier=tier, audited_page_count=audited_page_count)
    past_due = get_success_data(api_client.mark_past_due_subscription(
        sub["id"], TEST_USERS["platform_admin_headers"]))
    return org, past_due, site


def setup_subscription_suspended(tier="SCAN", audited_page_count=5):
    """Org + Site + subscription driven TRIAL->ACTIVE->PAST_DUE->SUSPENDED.
    Returns (org, subscription_after_suspend, site)."""
    org, past_due, site = setup_subscription_past_due(tier=tier, audited_page_count=audited_page_count)
    suspended = get_success_data(api_client.suspend_subscription(
        past_due["id"], TEST_USERS["platform_admin_headers"]))
    return org, suspended, site


# ─── Training lifecycle helpers ─────────────────────────────────────────────
def setup_training_in_progress():
    """Org + enrollment driven ENROLLED->IN_PROGRESS. Returns (org, enrollment)."""
    org = create_org()
    owner = make_org_admin_headers(org["id"])
    enr = get_success_data(api_client.create_training_enrollment(
        create_training_enrollment_payload(org["id"]), owner))
    in_progress = get_success_data(api_client.start_training_enrollment(enr["id"], owner))
    return org, in_progress
