"""Cyclic state machines: the finding retest revision loop and the incident
resolved -> reopened -> contained cycle.

Translation of SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rule
`non_linear_state_machine` instances `nonlinear_finding_retest_revision_cycle`
and `nonlinear_incident_resolved_reopen_contain_cycle`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, TEST_USERS,
)
from test_helpers import (
    create_client, create_asset, create_completed_scan, create_finding,
    create_promoted_incident, make_engagement_lead_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["engagement_lead_headers"]
SOC = TEST_USERS["soc_analyst_headers"]
CONTACT = TEST_USERS["client_contact_headers"]


# ─── nonlinear_finding_retest_revision_cycle ────────────────────────────────

def test_failing_retest_sends_finding_to_retest_failed(api):
    """PRD §3.5: "When retest_passed is false, the finding goes REMEDIATION_SUBMITTED → RETEST_FAILED."
    PRD §3.5: "The acting lead's X-User-ID must differ from the finding's
    submitted_by, or the retest is rejected with ERR_SEGREGATION_OF_DUTIES."

    Design: Difficulty/non_linear_state_machine/nonlinear_finding_retest_revision_cycle
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="MEDIUM")
    eng, scan = create_completed_scan(client["id"], [asset["id"]])
    finding = create_finding(scan["id"], asset["id"], cvss_base=5.0,
                            title="Loop", submitter_id="analyst-1")
    validate_success(api.start_remediation(finding["id"], CONTACT), 200)
    validate_success(api.submit_remediation(finding["id"], CONTACT), 200)
    res = api.retest_finding(finding["id"], {"retest_passed": False},
                             make_engagement_lead_headers("lead-1"))
    updated = validate_success(res, 200)
    assert updated["status"] == "RETEST_FAILED"


def test_retest_failed_loops_back_to_remediation_in_progress(api):
    """PRD §3.5: "A failed retest re-enters the loop: the same start-remediation
    action drives RETEST_FAILED → REMEDIATION_IN_PROGRESS, and the cycle repeats
    until a retest passes."

    Design: Difficulty/non_linear_state_machine/nonlinear_finding_retest_revision_cycle
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="MEDIUM")
    eng, scan = create_completed_scan(client["id"], [asset["id"]])
    finding = create_finding(scan["id"], asset["id"], cvss_base=5.0,
                            title="Loop", submitter_id="analyst-1")
    validate_success(api.start_remediation(finding["id"], CONTACT), 200)
    validate_success(api.submit_remediation(finding["id"], CONTACT), 200)
    validate_success(api.retest_finding(finding["id"], {"retest_passed": False},
                                        make_engagement_lead_headers("lead-1")), 200)
    looped = validate_success(api.start_remediation(finding["id"], CONTACT), 200)
    assert looped["status"] == "REMEDIATION_IN_PROGRESS"


# ─── nonlinear_incident_resolved_reopen_contain_cycle ───────────────────────

def test_resolved_incident_reopens_in_same_period(api):
    """PRD §3.7: "A resolved incident can be reopened by a SocAnalyst
    (RESOLVED → REOPENED), but only within the same billing period it was resolved
    in: the client's current_period_index must equal the incident's
    resolved_period_index."

    Design: Difficulty/non_linear_state_machine/nonlinear_incident_resolved_reopen_contain_cycle
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="CROWN_JEWEL", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], raw_score=90)
    api.acknowledge_incident(incident["id"], SOC)
    api.contain_incident(incident["id"], SOC, payload={"quarantine_asset": False})
    api.resolve_incident(incident["id"], {"response_hours": 4}, LEAD)
    reopened = validate_success(api.reopen_incident(incident["id"], SOC), 200)
    assert reopened["status"] == "REOPENED"


def test_reopened_incident_contains_again_increments_contained_count(api):
    """PRD §3.7: "A reopened incident can be contained again (REOPENED → CONTAINED),
    once more incrementing contained_count."
    PRD §3.7: "From ACKNOWLEDGED, a SocAnalyst contains it (ACKNOWLEDGED → CONTAINED), incrementing contained_count by one each time."

    Design: Difficulty/non_linear_state_machine/nonlinear_incident_resolved_reopen_contain_cycle
    """
    client = create_client()
    asset = create_asset(client["id"], criticality="CROWN_JEWEL", exposure="EXTERNAL")
    alert, incident = create_promoted_incident(client["id"], asset["id"], raw_score=90)
    api.acknowledge_incident(incident["id"], SOC)
    api.contain_incident(incident["id"], SOC, payload={"quarantine_asset": False})
    api.resolve_incident(incident["id"], {"response_hours": 4}, LEAD)
    api.reopen_incident(incident["id"], SOC)
    contained = validate_success(api.contain_incident(incident["id"], SOC), 200)
    assert contained["status"] == "CONTAINED"
    assert contained["contained_count"] == 2
