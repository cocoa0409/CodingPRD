"""Authorization-time and scan-time constraints: temporal overlap, cross-entity
state gates, validation-priority conflicts, and remaining validation rules.

Translations of SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rules:
 - `resource_temporal_overlap` instances `overlap_pentest_window_halfopen_adjacent_ok`,
   `overlap_scan_cooldown_closed_buffer_24h`.
 - `cross_entity_state_dependency` instances
   `cross_scan_start_requires_engagement_active`,
   `cross_audit_ready_requires_zero_open_critical_findings`.
 - `priority_pair_validation_conflict` instances
   `priority_conflict_lockdown_safety_beats_retainer_fiscal`,
   `priority_conflict_state_beats_segregation_safety_on_retest`.
and SCAFFOLD_CORNER_DESIGN.yaml queue B section `validations`:
   `scope_asset_invalid_when_decommissioned`, `duplicate_hostname_per_client...`,
   `promote_alert_inactive_client_returns_client_not_active`.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
)
from test_helpers import (
    create_client, create_asset, create_draft_engagement,
    create_authorized_engagement, create_active_engagement, queue_scan,
    create_completed_scan, create_finding, create_fieldwork_audit,
    submit_evidence, approve_evidence, create_triaged_alert,
    setup_lockdown_client, reset_clock, set_clock,
    make_engagement_lead_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LEAD = TEST_USERS["engagement_lead_headers"]
SOC = TEST_USERS["soc_analyst_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
CONTACT = TEST_USERS["client_contact_headers"]


@pytest.fixture(autouse=True)
def _clock():
    reset_clock()
    yield


# ─── overlap_pentest_window_halfopen_adjacent_ok ────────────────────────────

def test_pentest_overlapping_window_rejected(api):
    """PRD §3.3: "no other engagement of kind PENTEST in status AUTHORIZED or ACTIVE
    may share any asset in scope_asset_ids while its authorized window overlaps this
    one; windows are treated as half-open intervals ... and a genuine overlap is
    rejected with ERR_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/overlap_pentest_window_halfopen_adjacent_ok
    """
    client = create_client()
    asset = create_asset(client["id"], hostname="ov-01", criticality="MEDIUM")
    create_authorized_engagement(
        client["id"], [asset["id"]], kind="PENTEST", estimated_hours=5,
        window_start="2026-03-01T00:00:00Z", window_end="2026-03-10T00:00:00Z")
    eng_overlap = create_draft_engagement(
        client["id"], [asset["id"]], kind="PENTEST", estimated_hours=5,
        window_start="2026-03-05T00:00:00Z", window_end="2026-03-15T00:00:00Z")
    res = api.authorize_engagement(eng_overlap["id"], CONTACT)
    validate_error(res, "ERR_WINDOW_OVERLAP")


def test_pentest_adjacent_window_allowed(api):
    """PRD §3.3: "two windows where one's end exactly equals the other's start do not
    conflict."
    PRD §3.3: "windows are treated as half-open intervals running from
    authorized_window_start up to but not including authorized_window_end."

    Design: Difficulty/resource_temporal_overlap/overlap_pentest_window_halfopen_adjacent_ok
    """
    client = create_client()
    asset = create_asset(client["id"], hostname="ov-02", criticality="MEDIUM")
    create_authorized_engagement(
        client["id"], [asset["id"]], kind="PENTEST", estimated_hours=5,
        window_start="2026-03-01T00:00:00Z", window_end="2026-03-10T00:00:00Z")
    eng_adjacent = create_draft_engagement(
        client["id"], [asset["id"]], kind="PENTEST", estimated_hours=5,
        window_start="2026-03-10T00:00:00Z", window_end="2026-03-20T00:00:00Z")
    res = api.authorize_engagement(eng_adjacent["id"], CONTACT)
    authorized = validate_success(res, 200)
    assert authorized["status"] == "AUTHORIZED"


# ─── overlap_scan_cooldown_closed_buffer_24h ────────────────────────────────

def test_scan_within_24h_cooldown_rejected(api):
    """PRD §3.4: "no other scan in RUNNING status under the same engagement may have
    a closed buffered interval running from its started_at through 24 hours after
    its started_at that contains the clock — a new scan may not start within 24
    hours of another running scan on the same engagement — or the request is
    rejected with ERR_SCAN_WINDOW_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/overlap_scan_cooldown_closed_buffer_24h
    """
    client = create_client(retainer_hours_per_period=100)
    asset = create_asset(client["id"], hostname="cd-01", criticality="MEDIUM")
    eng = create_active_engagement(client["id"], [asset["id"]], estimated_hours=20)
    set_clock("2026-03-02T00:00:00Z")
    scan_a = queue_scan(eng["id"], eng["version"])
    validate_success(api.start_scan(scan_a["id"], LEAD), 200)
    eng_now = validate_success(api.get_engagement(eng["id"], LEAD), 200)
    scan_b = queue_scan(eng["id"], eng_now["version"])
    set_clock("2026-03-02T12:00:00Z")  # 12h after scan_a start, inside 24h buffer
    res = api.start_scan(scan_b["id"], LEAD)
    validate_error(res, "ERR_SCAN_WINDOW_OVERLAP")


def test_scan_at_exactly_24h_cooldown_still_collides(api):
    """PRD §3.4: "The interval is closed and buffered, so a clock landing exactly 24
    hours after another scan's start still collides."

    Design: Difficulty/resource_temporal_overlap/overlap_scan_cooldown_closed_buffer_24h
    """
    client = create_client(retainer_hours_per_period=100)
    asset = create_asset(client["id"], hostname="cd-02", criticality="MEDIUM")
    eng = create_active_engagement(client["id"], [asset["id"]], estimated_hours=20)
    set_clock("2026-03-02T00:00:00Z")
    scan_a = queue_scan(eng["id"], eng["version"])
    validate_success(api.start_scan(scan_a["id"], LEAD), 200)
    eng_now = validate_success(api.get_engagement(eng["id"], LEAD), 200)
    scan_b = queue_scan(eng["id"], eng_now["version"])
    set_clock("2026-03-03T00:00:00Z")  # exactly 24h after scan_a start (closed interval)
    res = api.start_scan(scan_b["id"], LEAD)
    validate_error(res, "ERR_SCAN_WINDOW_OVERLAP")


# ─── cross_scan_start_requires_engagement_active ────────────────────────────

def test_scan_start_on_authorized_engagement_returns_engagement_not_active(api):
    """PRD §3.4: "The parent engagement must be ACTIVE, or the request is rejected
    with ERR_ENGAGEMENT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/cross_scan_start_requires_engagement_active
    """
    client = create_client()
    asset = create_asset(client["id"], hostname="x1-01", criticality="MEDIUM")
    eng = create_authorized_engagement(client["id"], [asset["id"]])  # AUTHORIZED, not started
    scan = queue_scan(eng["id"], eng["version"])
    res = api.start_scan(scan["id"], LEAD)
    validate_error(res, "ERR_ENGAGEMENT_NOT_ACTIVE")


def test_scan_start_succeeds_on_active_engagement(api):
    """PRD §3.4: "Starting a queued scan advances QUEUED → RUNNING and is an
    EngagementLead action. The parent engagement must be ACTIVE."
    PRD §3.4: "On success the scan stamps started_at with the clock."

    Design: Difficulty/cross_entity_state_dependency/cross_scan_start_requires_engagement_active
    """
    client = create_client()
    asset = create_asset(client["id"], hostname="x1-02", criticality="MEDIUM")
    eng = create_active_engagement(client["id"], [asset["id"]])
    scan = queue_scan(eng["id"], eng["version"])
    started = validate_success(api.start_scan(scan["id"], LEAD), 200)
    assert started["status"] == "RUNNING"


# ─── cross_audit_ready_requires_zero_open_critical_findings ─────────────────

def _client_with_open_critical_and_ready_audit():
    """Client with one OPEN CRITICAL finding + an audit at 100.00 readiness in FIELDWORK."""
    client = create_client(retainer_hours_per_period=100)
    asset = create_asset(client["id"], hostname="x2-01", criticality="MEDIUM")
    eng, scan = create_completed_scan(client["id"], [asset["id"]])
    finding = create_finding(scan["id"], asset["id"], cvss_base=9.5, title="Crit")
    audit = create_fieldwork_audit(client["id"], framework="PCI", required_control_count=1)
    ev = submit_evidence(audit["id"], audit["version"], control_ref="CC6.1",
                        submitter_id="lead-sub")
    approve_evidence(ev["id"], approver_id="auditor-appr")
    audit = validate_success(api_client.get_audit(audit["id"], AUDITOR), 200)
    return client, finding, audit


def test_mark_ready_blocked_by_open_critical_findings(api):
    """PRD §3.8: "the client's open_critical_findings must be zero, or it is rejected
    with ERR_OPEN_CRITICAL_FINDINGS — an audit cannot go ready while its client
    still has open critical findings."

    Design: Difficulty/cross_entity_state_dependency/cross_audit_ready_requires_zero_open_critical_findings
    """
    client, finding, audit = _client_with_open_critical_and_ready_audit()
    assert finding["severity"] == "CRITICAL"
    assert audit["readiness_pct"] == pytest.approx(100.00, abs=0.001)
    res = api.mark_ready(audit["id"], AUDITOR)
    validate_error(res, "ERR_OPEN_CRITICAL_FINDINGS")


def test_client_open_critical_findings_count_reflects_open_critical(api):
    """PRD §2.8: "A client also carries a computed open_critical_findings count — the
    number of findings whose severity is CRITICAL and whose status is none of
    REMEDIATED, RISK_ACCEPTED, or FALSE_POSITIVE."

    Design: Difficulty/cross_entity_state_dependency/cross_audit_ready_requires_zero_open_critical_findings
    """
    client, finding, audit = _client_with_open_critical_and_ready_audit()
    fetched = validate_success(api.get_client(client["id"], ADMIN), 200)
    assert fetched["open_critical_findings"] == 1


# ─── priority_conflict_lockdown_safety_beats_retainer_fiscal ────────────────

def test_authorize_lockdown_and_over_budget_returns_posture_lockdown(api):
    """PRD §2.10: "and only then the business-safety, referential, temporal, and
    fiscal checks specific to the operation."
    PRD §3.3: "The client must not be in LOCKDOWN, or the request is rejected with
    ERR_POSTURE_LOCKDOWN."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_lockdown_safety_beats_retainer_fiscal
    """
    # Client retainer 10h, in LOCKDOWN; a DRAFT engagement estimated_hours 50.
    client = create_client(retainer_hours_per_period=10)
    asset = create_asset(client["id"], hostname="dual-01", criticality="CROWN_JEWEL",
                        exposure="EXTERNAL")
    from test_helpers import create_promoted_incident
    alert, incident = create_promoted_incident(client["id"], asset["id"], raw_score=90)
    api.escalate_incident(incident["id"], LEAD)  # posture -> LOCKDOWN
    eng = create_draft_engagement(client["id"], [asset["id"]], estimated_hours=50)
    res = api.authorize_engagement(eng["id"], CONTACT)
    # Both LOCKDOWN (business-safety) and over-budget (fiscal) hold; safety wins.
    validate_error(res, "ERR_POSTURE_LOCKDOWN")


def test_authorize_over_budget_with_open_posture_returns_retainer_exhausted(api):
    """PRD §2.10: "and only then the business-safety, referential, temporal, and
    fiscal checks specific to the operation."
    PRD §3.3: "its hours_available must be at least the engagement's estimated_hours,
    or the request is rejected with ERR_RETAINER_EXHAUSTED."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_lockdown_safety_beats_retainer_fiscal
    """
    # Same fiscal over-budget condition, but posture is OPEN (no escalated incident):
    # the lower-priority fiscal check surfaces only once the safety check passes.
    client = create_client(retainer_hours_per_period=10)
    asset = create_asset(client["id"], hostname="dual-02", criticality="CROWN_JEWEL",
                        exposure="EXTERNAL")
    eng = create_draft_engagement(client["id"], [asset["id"]], estimated_hours=50)
    res = api.authorize_engagement(eng["id"], CONTACT)
    validate_error(res, "ERR_RETAINER_EXHAUSTED")


# ─── priority_conflict_state_beats_segregation_safety_on_retest ─────────────

def test_retest_on_open_finding_by_submitter_returns_invalid_state(api):
    """PRD §2.10: "a wrong current state surfaces as ERR_INVALID_STATE (HTTP 409)
    before any operation-specific business rule (posture lockdown, segregation of
    duties, window, retainer, and the rest) is evaluated."
    PRD §3.5: "An EngagementLead retests, supplying retest_passed; ... When
    retest_passed is true, it goes REMEDIATION_SUBMITTED → REMEDIATED."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_beats_segregation_safety_on_retest
    """
    client = create_client()
    asset = create_asset(client["id"], hostname="seg-01", criticality="MEDIUM")
    eng, scan = create_completed_scan(client["id"], [asset["id"]])
    # Finding submitted by the SAME user that will attempt the retest, left OPEN.
    finding = create_finding(scan["id"], asset["id"], cvss_base=5.0, title="Both",
                            submitter_id="lead-x")
    res = api.retest_finding(finding["id"], {"retest_passed": True},
                             make_engagement_lead_headers("lead-x"))
    # Finding is OPEN (not REMEDIATION_SUBMITTED): state check (priority 7) fires
    # before the segregation check (priority 9), even though submitter == actor.
    validate_error(res, "ERR_INVALID_STATE")


def test_retest_on_submitted_finding_by_submitter_returns_segregation(api):
    """PRD §3.5: "The acting lead's X-User-ID must differ from the finding's
    submitted_by, or the retest is rejected with ERR_SEGREGATION_OF_DUTIES."
    PRD §2.10: "a wrong current state surfaces as ERR_INVALID_STATE (HTTP 409)
    before any operation-specific business rule (posture lockdown, segregation of
    duties, window, retainer, and the rest) is evaluated."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_state_beats_segregation_safety_on_retest
    """
    # Now the finding IS in a state retest is allowed from (REMEDIATION_SUBMITTED),
    # so the state check (priority 7) passes and the lower-priority segregation
    # check (priority 9) is the one that fires for a same-user retest.
    client = create_client()
    asset = create_asset(client["id"], hostname="seg-02", criticality="MEDIUM")
    eng, scan = create_completed_scan(client["id"], [asset["id"]])
    finding = create_finding(scan["id"], asset["id"], cvss_base=5.0, title="Seg",
                            submitter_id="lead-y")
    api.start_remediation(finding["id"], CONTACT)
    api.submit_remediation(finding["id"], CONTACT)
    res = api.retest_finding(finding["id"], {"retest_passed": True},
                             make_engagement_lead_headers("lead-y"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES")


# ─── validations: scope_asset_invalid, duplicate_hostname, client_not_active ─

def test_authorize_with_decommissioned_scope_asset_returns_scope_asset_invalid(api):
    """PRD §3.3: "Every id in scope_asset_ids must be an ACTIVE asset belonging to
    this engagement's client, or the request is rejected with
    ERR_SCOPE_ASSET_INVALID."

    Design: Corner/validations/scope_asset_invalid_when_decommissioned
    """
    client = create_client()
    asset = create_asset(client["id"], hostname="val2-01", criticality="MEDIUM")
    api.decommission_asset(asset["id"], ADMIN)
    eng = create_draft_engagement(client["id"], [asset["id"]], kind="PENTEST",
                                  estimated_hours=5)
    res = api.authorize_engagement(eng["id"], CONTACT)
    validate_error(res, "ERR_SCOPE_ASSET_INVALID")


def test_duplicate_hostname_per_client_returns_duplicate_hostname(api):
    """PRD §3.2: "The hostname must be unique per client among assets that are not
    DECOMMISSIONED; a collision is rejected with ERR_DUPLICATE_HOSTNAME (HTTP 409)."

    Design: Corner/validations/duplicate_hostname_per_client_returns_duplicate_hostname
    """
    client = create_client(retainer_hours_per_period=50)
    create_asset(client["id"], hostname="dup-host", ip_address="10.0.5.3",
                criticality="LOW")
    from test_helpers import create_asset_payload
    res = api.create_asset(
        create_asset_payload(client["id"], hostname="dup-host", ip_address="10.0.5.4",
                            criticality="LOW"), ADMIN)
    validate_error(res, "ERR_DUPLICATE_HOSTNAME")


def test_promote_alert_suspended_client_returns_client_not_active(api):
    """PRD §3.6: "Promotion is a SocAnalyst action advancing TRIAGED → PROMOTED,
    permitted only when the client's status is ACTIVE, else ERR_CLIENT_NOT_ACTIVE."

    Design: Corner/validations/promote_alert_inactive_client_returns_client_not_active
    """
    client = create_client(retainer_hours_per_period=50)
    asset = create_asset(client["id"], hostname="val4-01", criticality="HIGH",
                        exposure="EXTERNAL")
    alert = create_triaged_alert(client["id"], asset["id"], raw_score=80)
    api.suspend_client(client["id"], ADMIN)
    res = api.promote_alert(alert["id"], SOC)
    validate_error(res, "ERR_CLIENT_NOT_ACTIVE")
