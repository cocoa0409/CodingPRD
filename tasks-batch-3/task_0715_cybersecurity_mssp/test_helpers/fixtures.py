"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures. Every
helper builds its preconditions from scratch via PRD-declared endpoints, because
the database is empty at the start of every test.

Roles are opaque (PRD §2.1): the X-User-ID is never compared to an entity id, so
ownership threading is not required; where segregation-of-duties matters the
caller passes distinct user_ids via the make_*_headers builders.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_client_payload, create_asset_payload, create_engagement_payload,
    create_scan_payload, complete_scan_payload, create_finding_payload,
    create_alert_payload, contain_payload, resolve_payload,
    create_audit_payload, create_evidence_payload, create_report_payload,
)
from .test_users import (
    TEST_USERS,
    make_engagement_lead_headers, make_soc_analyst_headers,
    make_auditor_headers,
)
from .constants import DEFAULT_CLOCK

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["engagement_lead_headers"]
SOC = TEST_USERS["soc_analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
CONTACT = TEST_USERS["client_contact_headers"]


# ─── Clock helpers ────────────────────────────────────────────────────────

def reset_clock():
    """Reset the logical clock to the PRD startup default."""
    return get_success_data(api_client.set_clock(DEFAULT_CLOCK, ADMIN))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1/2: base entities ──────────────────────────────────────────────

def create_client(tier="ESSENTIAL", retainer_hours_per_period=100, name="Test Client"):
    """Create a client (and its period-0 OPEN ledger). Returns the Client dict."""
    return get_success_data(api_client.create_client(
        create_client_payload(name=name, tier=tier,
                              retainer_hours_per_period=retainer_hours_per_period),
        ADMIN))


def create_asset(client_id, hostname="host-01", ip_address="10.0.0.1",
                 criticality="MEDIUM", exposure=None):
    """Create an ACTIVE asset under a client. Returns the Asset dict."""
    overrides = {"hostname": hostname, "ip_address": ip_address, "criticality": criticality}
    if exposure is not None:
        overrides["exposure"] = exposure
    return get_success_data(api_client.create_asset(
        create_asset_payload(client_id, **overrides), ADMIN))


def get_period_ledger(client_id, period_index=0):
    """Read back the RetainerLedger row for (client_id, period_index)."""
    res = api_client.list_retainer_ledgers(
        ADMIN, params={"client_id": client_id, "period_index": period_index})
    data = get_success_data(res)
    rows = data if isinstance(data, list) else data.get("data", data)
    assert rows, f"no ledger for client {client_id} period {period_index}"
    return rows[0]


# ─── Engagement lifecycle shortcuts ───────────────────────────────────────

def create_draft_engagement(client_id, scope_asset_ids, kind="VULN_SCAN",
                            estimated_hours=10,
                            window_start="2026-03-01T00:00:00Z",
                            window_end="2026-04-01T00:00:00Z"):
    """Create a DRAFT engagement. Returns the Engagement dict."""
    return get_success_data(api_client.create_engagement(
        create_engagement_payload(
            client_id, scope_asset_ids, kind=kind, estimated_hours=estimated_hours,
            authorized_window_start=window_start, authorized_window_end=window_end),
        LEAD))


def create_authorized_engagement(client_id, scope_asset_ids, kind="VULN_SCAN",
                                 estimated_hours=10,
                                 window_start="2026-03-01T00:00:00Z",
                                 window_end="2026-04-01T00:00:00Z"):
    """Create + authorize an engagement (reserves retainer). Returns AUTHORIZED Engagement."""
    eng = create_draft_engagement(client_id, scope_asset_ids, kind, estimated_hours,
                                  window_start, window_end)
    return get_success_data(api_client.authorize_engagement(eng["id"], CONTACT))


def create_active_engagement(client_id, scope_asset_ids, kind="VULN_SCAN",
                            estimated_hours=10,
                            window_start="2026-03-01T00:00:00Z",
                            window_end="2026-04-01T00:00:00Z"):
    """Create + authorize + start an engagement. Returns ACTIVE Engagement."""
    eng = create_authorized_engagement(client_id, scope_asset_ids, kind, estimated_hours,
                                       window_start, window_end)
    return get_success_data(api_client.start_engagement(eng["id"], LEAD))


def queue_scan(engagement_id, expected_engagement_version):
    """Queue a scan under an engagement with the supplied OCC version. Returns Scan."""
    return get_success_data(api_client.create_scan(
        create_scan_payload(engagement_id, expected_engagement_version), LEAD))


def create_completed_scan(client_id, scope_asset_ids, estimated_hours=10,
                          actual_hours=5, raw_finding_count=1, kind="VULN_SCAN"):
    """
    Full chain to a COMPLETED scan from an empty client:
    authorize + start engagement -> queue scan -> start scan -> complete scan.
    Returns (engagement, scan). The engagement is ACTIVE.
    """
    eng = create_active_engagement(client_id, scope_asset_ids,
                                   kind=kind, estimated_hours=estimated_hours)
    scan = queue_scan(eng["id"], eng["version"])
    get_success_data(api_client.start_scan(scan["id"], LEAD))
    scan = get_success_data(api_client.complete_scan(
        scan["id"], complete_scan_payload(actual_hours, raw_finding_count=raw_finding_count),
        LEAD))
    return eng, scan


# ─── Finding shortcuts ────────────────────────────────────────────────────

def create_finding(scan_id, asset_id, cvss_base=5.0, title="Test Finding",
                   submitter_id="submitter-1"):
    """Record a finding against a COMPLETED scan (SocAnalyst with a chosen user_id)."""
    headers = make_soc_analyst_headers(submitter_id)
    return get_success_data(api_client.create_finding(
        create_finding_payload(scan_id, asset_id, cvss_base=cvss_base, title=title),
        headers))


def setup_client_with_finding(cvss_base=5.0, criticality="MEDIUM", tier="ESSENTIAL",
                              submitter_id="submitter-1", retainer_hours=100):
    """
    Empty DB -> Client + ACTIVE asset + COMPLETED scan + one OPEN finding.
    Returns (client, asset, engagement, scan, finding).
    """
    client = create_client(tier=tier, retainer_hours_per_period=retainer_hours)
    asset = create_asset(client["id"], criticality=criticality)
    eng, scan = create_completed_scan(client["id"], [asset["id"]])
    finding = create_finding(scan["id"], asset["id"], cvss_base=cvss_base,
                            submitter_id=submitter_id)
    return client, asset, eng, scan, finding


def drive_finding_to_submitted(finding_id):
    """OPEN -> REMEDIATION_IN_PROGRESS -> REMEDIATION_SUBMITTED (ClientContact)."""
    get_success_data(api_client.start_remediation(finding_id, CONTACT))
    return get_success_data(api_client.submit_remediation(finding_id, CONTACT))


# ─── Alert / Incident shortcuts ───────────────────────────────────────────

def create_alert(client_id, asset_id, source="SIEM", raw_score=50):
    """Ingest an alert. Returns Alert dict (triage_priority computed)."""
    return get_success_data(api_client.create_alert(
        create_alert_payload(client_id, asset_id, source=source, raw_score=raw_score),
        SOC))


def create_triaged_alert(client_id, asset_id, source="SIEM", raw_score=50):
    """Ingest + triage an alert. Returns TRIAGED Alert dict."""
    alert = create_alert(client_id, asset_id, source=source, raw_score=raw_score)
    return get_success_data(api_client.triage_alert(alert["id"], SOC))


def create_promoted_incident(client_id, asset_id, source="SIEM", raw_score=90):
    """
    Ingest + triage + promote an alert into an incident.
    Returns (alert, incident) — incident is DETECTED with severity mapped from priority.
    """
    alert = create_triaged_alert(client_id, asset_id, source=source, raw_score=raw_score)
    alert = get_success_data(api_client.promote_alert(alert["id"], SOC))
    incident = get_success_data(
        api_client.get_incident(alert["promoted_incident_id"], SOC))
    return alert, incident


def setup_lockdown_client(retainer_hours=100):
    """
    Empty DB -> Client driven into LOCKDOWN via a CRITICAL incident escalation.
    Returns (client, asset, incident). incident is ESCALATED, client posture LOCKDOWN.
    """
    client = create_client(retainer_hours_per_period=retainer_hours)
    asset = create_asset(client["id"], criticality="CROWN_JEWEL", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"],
                                               source="SIEM", raw_score=90)
    incident = get_success_data(api_client.escalate_incident(incident["id"], LEAD))
    return client, asset, incident


# ─── Compliance audit / evidence shortcuts ────────────────────────────────

def create_fieldwork_audit(client_id, framework="SOC2", required_control_count=1):
    """Create an audit + begin fieldwork. Returns FIELDWORK ComplianceAudit dict."""
    audit = get_success_data(api_client.create_audit(
        create_audit_payload(client_id, framework=framework,
                            required_control_count=required_control_count),
        AUDITOR))
    return get_success_data(api_client.begin_fieldwork(audit["id"], AUDITOR))


def submit_evidence(audit_id, expected_audit_version, control_ref="CC6.1",
                    submitter_id="ev-submitter-1"):
    """Submit evidence with the supplied OCC version. Returns SUBMITTED AuditEvidence."""
    headers = make_auditor_headers(submitter_id)
    return get_success_data(api_client.create_evidence(
        create_evidence_payload(audit_id, expected_audit_version, control_ref=control_ref),
        headers))


def approve_evidence(evidence_id, approver_id="ev-approver-1"):
    """Approve evidence as an Auditor distinct from the submitter."""
    headers = make_auditor_headers(approver_id)
    return get_success_data(api_client.approve_evidence(evidence_id, headers))


def setup_ready_audit(client_id, required_control_count=1,
                      submitter_id="ev-submitter-1", approver_id="ev-approver-1"):
    """
    Audit in FIELDWORK with `required_control_count` controls each covered by one
    APPROVED evidence item (distinct control_refs), reaching readiness_pct 100.00.
    Returns (audit, [evidence...]). Audit is still in FIELDWORK (not marked ready).
    """
    audit = create_fieldwork_audit(client_id, required_control_count=required_control_count)
    version = audit["version"]
    evidences = []
    for i in range(required_control_count):
        ev = submit_evidence(audit["id"], version, control_ref=f"CC{i + 1}.0",
                            submitter_id=submitter_id)
        approved = approve_evidence(ev["id"], approver_id=approver_id)
        evidences.append(approved)
        # Each approve recomputes readiness and bumps audit version; re-read it.
        audit = get_success_data(api_client.get_audit(audit["id"], AUDITOR))
        version = audit["version"]
    return audit, evidences


# ─── Report shortcut ──────────────────────────────────────────────────────

def create_report(client_id, kind="ASSESSMENT"):
    """Generate a report. Returns GENERATED Report dict."""
    return get_success_data(api_client.create_report(
        create_report_payload(client_id, kind=kind), LEAD))
