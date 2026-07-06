"""State-machine transition guards, terminal-state lockdown, and report endpoints.

Translations of SCAFFOLD_CORNER_DESIGN.yaml queue B sections `state_machines`
and `endpoints`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
)
from test_helpers import (
    create_client, create_asset, create_promoted_incident, create_triaged_alert,
    create_completed_scan, create_finding, drive_finding_to_submitted,
    create_draft_engagement, create_report, setup_lockdown_client,
    make_soc_analyst_headers, make_engagement_lead_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["engagement_lead_headers"]
SOC = TEST_USERS["soc_analyst_headers"]
CONTACT = TEST_USERS["client_contact_headers"]


def test_acknowledge_resolved_incident_returns_invalid_state(api):
    """PRD §2.10: "a wrong current state surfaces as ERR_INVALID_STATE (HTTP 409)."
    PRD §3.7: "A SocAnalyst acknowledges an incident (DETECTED → ACKNOWLEDGED)."

    Design: Corner/state_machines/acknowledge_incident_from_resolved_returns_invalid_state
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="CROWN_JEWEL", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], raw_score=90)
    api.acknowledge_incident(incident["id"], SOC)
    api.contain_incident(incident["id"], SOC, payload={"quarantine_asset": False})
    api.resolve_incident(incident["id"], {"response_hours": 1}, LEAD)

    res = api.acknowledge_incident(incident["id"], SOC)
    validate_error(res, "ERR_INVALID_STATE")
    after = validate_success(api.get_incident(incident["id"], SOC), 200)
    assert after["status"] == "RESOLVED"


def test_dismiss_p1_alert_returns_cannot_dismiss_high_priority(api):
    """PRD §3.6: "a SocAnalyst dismisses an alert (TRIAGED → DISMISSED), but only
    when its triage_priority is P3 or P4; P1 and P2 alerts must be promoted rather
    than dismissed, and an attempt to dismiss one is rejected with
    ERR_CANNOT_DISMISS_HIGH_PRIORITY."

    Design: Corner/state_machines/dismiss_high_priority_alert_returns_cannot_dismiss
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="CROWN_JEWEL", exposure="EXTERNAL")
    alert = create_triaged_alert(client["id"], asset["id"], raw_score=90)
    assert alert["triage_priority"] == "P1"
    res = api.dismiss_alert(alert["id"], SOC)
    validate_error(res, "ERR_CANNOT_DISMISS_HIGH_PRIORITY")


def test_escalate_low_severity_incident_returns_cannot_escalate_low(api):
    """PRD §3.7: "Escalation is an EngagementLead action available from either
    DETECTED or ACKNOWLEDGED ..., permitted only when the incident's severity is
    HIGH or CRITICAL; escalating a LOW or MEDIUM incident is rejected with
    ERR_CANNOT_ESCALATE_LOW."

    Design: Corner/state_machines/escalate_low_severity_incident_returns_cannot_escalate
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="LOW", exposure="INTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], source="EDR",
                                               raw_score=40)
    assert incident["severity"] == "LOW"
    res = api.escalate_incident(incident["id"], LEAD)
    validate_error(res, "ERR_CANNOT_ESCALATE_LOW")


def test_accept_risk_critical_finding_returns_cannot_accept_critical(api):
    """PRD §3.5: "A ClientContact may risk-accept a finding (OPEN → RISK_ACCEPTED),
    but only when the finding's severity is not CRITICAL; an attempt to risk-accept
    a CRITICAL finding is rejected with ERR_CANNOT_ACCEPT_CRITICAL."

    Design: Corner/state_machines/accept_risk_critical_finding_returns_cannot_accept_critical
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="MEDIUM")
    eng, scan = create_completed_scan(client["id"], [asset["id"]])
    finding = create_finding(scan["id"], asset["id"], cvss_base=9.5)
    assert finding["severity"] == "CRITICAL"
    res = api.accept_risk(finding["id"], CONTACT)
    validate_error(res, "ERR_CANNOT_ACCEPT_CRITICAL")


def test_complete_engagement_with_queued_scan_returns_scans_in_flight(api):
    """PRD §3.3: "Completing an engagement is an EngagementLead action advancing
    ACTIVE → COMPLETED; it is blocked while any scan under the engagement is still
    QUEUED or RUNNING, which surfaces as ERR_SCANS_IN_FLIGHT."

    Design: Corner/state_machines/scan_complete_with_scans_in_flight_blocks_engagement_complete
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="MEDIUM")
    from test_helpers import create_active_engagement, queue_scan
    eng = create_active_engagement(client["id"], [asset["id"]])
    queue_scan(eng["id"], eng["version"])  # QUEUED, never started
    res = api.complete_engagement(eng["id"], LEAD)
    validate_error(res, "ERR_SCANS_IN_FLIGHT")


def test_triage_alert_on_decommissioned_asset_returns_asset_decommissioned(api):
    """PRD §3.6: "Its asset must resolve to an asset whose status is not
    DECOMMISSIONED, or the request is rejected with ERR_ASSET_DECOMMISSIONED."

    Design: Corner/state_machines/triage_alert_on_decommissioned_asset_returns_asset_decommissioned
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="MEDIUM")
    from test_helpers import create_alert
    alert = create_alert(client["id"], asset["id"], source="EDR", raw_score=50)
    api.decommission_asset(asset["id"], ADMIN)
    res = api.triage_alert(alert["id"], SOC)
    validate_error(res, "ERR_ASSET_DECOMMISSIONED")


def test_reopen_incident_in_later_period_returns_reopen_window_closed(api):
    """PRD §3.7: "A resolved incident can be reopened by a SocAnalyst
    (RESOLVED → REOPENED), but only within the same billing period it was resolved
    in: the client's current_period_index must equal the incident's
    resolved_period_index, or the reopen is rejected with ERR_REOPEN_WINDOW_CLOSED."

    Design: Corner/state_machines/reopen_incident_in_later_period_returns_reopen_window_closed
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="CROWN_JEWEL", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], raw_score=90)
    api.acknowledge_incident(incident["id"], SOC)
    api.contain_incident(incident["id"], SOC, payload={"quarantine_asset": False})
    api.resolve_incident(incident["id"], {"response_hours": 2}, LEAD)
    api.advance_period(client["id"], ADMIN)  # now period 1
    res = api.reopen_incident(incident["id"], SOC)
    validate_error(res, "ERR_REOPEN_WINDOW_CLOSED")


def test_start_engagement_before_window_returns_outside_window(api):
    """PRD §3.3: "Beginning sanctioned testing is an EngagementLead action that
    advances AUTHORIZED → ACTIVE. It is permitted only when the logical clock is
    at or after authorized_window_start and at or before authorized_window_end —
    otherwise ERR_OUTSIDE_WINDOW."

    Design: Corner/state_machines/start_engagement_outside_window_returns_outside_window
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="MEDIUM")
    from test_helpers import create_authorized_engagement
    eng = create_authorized_engagement(client["id"], [asset["id"]],
                                       window_start="2026-03-15T00:00:00Z",
                                       window_end="2026-04-01T00:00:00Z")
    # default clock 2026-03-01 is before window start 2026-03-15
    res = api.start_engagement(eng["id"], LEAD)
    validate_error(res, "ERR_OUTSIDE_WINDOW")


def test_remediated_finding_rejects_further_start_remediation(api):
    """PRD §2.10: "a wrong current state surfaces as ERR_INVALID_STATE (HTTP 409)."
    PRD §3.5: "when retest_passed is true, it goes REMEDIATION_SUBMITTED → REMEDIATED, stamping accepted_by with the lead's X-User-ID."

    Design: Corner/state_machines/terminal_finding_remediated_no_further_transition
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="MEDIUM")
    eng, scan = create_completed_scan(client["id"], [asset["id"]])
    finding = create_finding(scan["id"], asset["id"], cvss_base=5.0,
                            submitter_id="analyst-9")
    drive_finding_to_submitted(finding["id"])
    api.retest_finding(finding["id"], {"retest_passed": True},
                       make_engagement_lead_headers("lead-9"))
    after = validate_success(api.get_finding(finding["id"], LEAD), 200)
    assert after["status"] == "REMEDIATED"
    res = api.start_remediation(finding["id"], CONTACT)
    validate_error(res, "ERR_INVALID_STATE")


# ─── endpoints section ──────────────────────────────────────────────────────

def test_publish_report_in_lockdown_returns_posture_lockdown(api):
    """PRD §3.9: "An EngagementLead publishes a report (GENERATED → PUBLISHED), but
    publication is blocked while the client is in LOCKDOWN, surfacing as
    ERR_POSTURE_LOCKDOWN."

    Design: Corner/endpoints/report_publish_blocked_in_lockdown
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="CROWN_JEWEL", exposure="EXTERNAL")
    report = create_report(client["id"], kind="ASSESSMENT")
    # Drive client to LOCKDOWN via an escalated incident on the same asset.
    alert, incident = create_promoted_incident(client["id"], asset["id"], raw_score=90)
    api.escalate_incident(incident["id"], LEAD)
    res = api.publish_report(report["id"], LEAD)
    validate_error(res, "ERR_POSTURE_LOCKDOWN")


def test_generate_report_freezes_snapshot(api):
    """PRD §3.9: "Generation freezes a denormalized snapshot of the current metrics
    — counts, hours, and readiness — into the report. A report opens in GENERATED."

    Design: Corner/endpoints/report_generate_then_retrieve_snapshot
    """
    client = create_client()
    res = api.create_report({"client_id": client["id"], "kind": "RETAINER"}, LEAD)
    report = validate_success(res, 201)
    assert report["status"] == "GENERATED"
    fetched = validate_success(api.get_report(report["id"], LEAD), 200)
    assert fetched["status"] == "GENERATED"
    assert fetched["snapshot"] is not None
    assert isinstance(fetched["snapshot"], dict)
