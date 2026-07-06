"""Transitive cascades (promote -> incident -> escalate -> posture LOCKDOWN;
contain -> quarantine) and the quarantine-conservation invariant on resolve.

Translations of SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rules:
 - `transitive_cascade` instances
   `cascade_alert_promote_incident_escalate_lockdown_depth3`,
   `cascade_incident_contain_quarantine_asset_depth2`.
 - `compensating_invariant` instance
   `invariant_asset_quarantine_conserved_on_resolve`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
)
from test_helpers import (
    create_client, create_asset, create_promoted_incident, create_draft_engagement,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["engagement_lead_headers"]
SOC = TEST_USERS["soc_analyst_headers"]
CONTACT = TEST_USERS["client_contact_headers"]


# ─── cascade_alert_promote_incident_escalate_lockdown_depth3 ────────────────

def test_escalate_drives_client_posture_to_lockdown(api):
    """PRD §3.7: "Escalation recomputes the client's posture into LOCKDOWN, freezing
    new engagement authorizations and starts and report publication until the
    escalation clears."
    PRD §2.8: "rises to LOCKDOWN when any incident is in the ESCALATED state."

    Design: Difficulty/transitive_cascade/cascade_alert_promote_incident_escalate_lockdown_depth3
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="CROWN_JEWEL", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], raw_score=90)
    escalated = validate_success(api.escalate_incident(incident["id"], LEAD), 200)
    assert escalated["status"] == "ESCALATED"
    client_after = validate_success(api.get_client(client["id"], ADMIN), 200)
    assert client_after["posture"] == "LOCKDOWN"


def test_lockdown_from_escalation_blocks_subsequent_authorize(api):
    """PRD §2.8: "While a client is in LOCKDOWN, new engagement authorizations are
    frozen ...; each such attempt is rejected with ERR_POSTURE_LOCKDOWN (HTTP 409)."
    PRD §3.3: "The client must not be in LOCKDOWN, or the request is rejected with
    ERR_POSTURE_LOCKDOWN."

    Design: Difficulty/transitive_cascade/cascade_alert_promote_incident_escalate_lockdown_depth3
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="CROWN_JEWEL", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], raw_score=90)
    eng = create_draft_engagement(client["id"], [asset["id"]])
    api.escalate_incident(incident["id"], LEAD)
    res = api.authorize_engagement(eng["id"], CONTACT)
    validate_error(res, "ERR_POSTURE_LOCKDOWN")


# ─── cascade_incident_contain_quarantine_asset_depth2 ───────────────────────

def test_contain_with_quarantine_sets_asset_quarantined(api):
    """PRD §3.7: "when true, the triggering alert's asset must be ACTIVE, and
    containment sets that asset's status to QUARANTINED and records its id in the
    incident's quarantined_asset_id — a cross-entity cascade."

    Design: Difficulty/transitive_cascade/cascade_incident_contain_quarantine_asset_depth2
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="HIGH", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], source="EDR",
                                               raw_score=80)
    api.acknowledge_incident(incident["id"], SOC)
    api.contain_incident(incident["id"], SOC, payload={"quarantine_asset": True})
    asset_after = validate_success(api.get_asset(asset["id"], ADMIN), 200)
    assert asset_after["status"] == "QUARANTINED"


def test_contain_with_quarantine_records_quarantined_asset_id(api):
    """PRD §3.7: "containment sets that asset's status to QUARANTINED and records its
    id in the incident's quarantined_asset_id — a cross-entity cascade."

    Design: Difficulty/transitive_cascade/cascade_incident_contain_quarantine_asset_depth2
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="HIGH", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], source="EDR",
                                               raw_score=80)
    api.acknowledge_incident(incident["id"], SOC)
    contained = validate_success(
        api.contain_incident(incident["id"], SOC, payload={"quarantine_asset": True}), 200)
    assert contained["quarantined_asset_id"] == asset["id"]


# ─── invariant_asset_quarantine_conserved_on_resolve ────────────────────────

def test_resolve_restores_quarantined_asset_to_active(api):
    """PRD §3.7: "If the incident had quarantined an asset, resolution reverses that
    quarantine — setting that asset's status back to ACTIVE and clearing
    quarantined_asset_id — as a compensating action that keeps quarantine
    accounting conserved."

    Design: Difficulty/compensating_invariant/invariant_asset_quarantine_conserved_on_resolve
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="HIGH", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], source="EDR",
                                               raw_score=80)
    api.acknowledge_incident(incident["id"], SOC)
    api.contain_incident(incident["id"], SOC, payload={"quarantine_asset": True})
    quar = validate_success(api.get_asset(asset["id"], ADMIN), 200)
    assert quar["status"] == "QUARANTINED"

    api.resolve_incident(incident["id"], {"response_hours": 3}, LEAD)
    restored = validate_success(api.get_asset(asset["id"], ADMIN), 200)
    assert restored["status"] == "ACTIVE"


def test_resolve_clears_quarantined_asset_id(api):
    """PRD §3.7: "setting that asset's status back to ACTIVE and clearing
    quarantined_asset_id — as a compensating action that keeps quarantine accounting
    conserved."

    Design: Difficulty/compensating_invariant/invariant_asset_quarantine_conserved_on_resolve
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="HIGH", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], source="EDR",
                                               raw_score=80)
    api.acknowledge_incident(incident["id"], SOC)
    api.contain_incident(incident["id"], SOC, payload={"quarantine_asset": True})
    resolved = validate_success(
        api.resolve_incident(incident["id"], {"response_hours": 3}, LEAD), 200)
    assert resolved["quarantined_asset_id"] is None
