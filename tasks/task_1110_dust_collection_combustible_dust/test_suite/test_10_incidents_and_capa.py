"""Incident investigation and CAPA: clock-driven OVERDUE actions, the
capa_open_count gate at close, and the reopen/resume cycle."""
from test_helpers import (
    ApiErrorId,
    create_capa,
    create_closed_incident,
    create_incident,
    create_site,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers.test_users import make_incident_investigator_headers

ENGINEER = TEST_USERS["compliance_engineer_headers"]
MANAGER = TEST_USERS["compliance_manager_headers"]
INVESTIGATOR = TEST_USERS["incident_investigator_headers"]


def test_capa_action_overdue_via_clock(api):
    """PRD §3.9: "When the clock advances past `due_at` while an action is
    `OPEN` or `IN_PROGRESS`, the system auto-transitions it to `OVERDUE` and
    recomputes posture."
    PRD §3.9: "Creating one increments the incident's `capa_count` and
    `capa_open_count` by 1."
    PRD §2.11: "Advancing the clock triggers any system-initiated transitions
    whose preconditions have become true: HousekeepingAudits that should flip
    to `OVERDUE`, HotWorkPermits that should flip to `EXPIRED`, CAPAActions
    that should flip to `OVERDUE`, and any downstream recomputation of
    `HousekeepingProgram.current_posture` and `Site.posture` that those
    transitions imply."

    The OVERDUE action is still open, so capa_open_count stays 1.

    Design: Corner/state_machines/capa_action_overdue_auto_transition_via_clock
    """
    set_clock("2026-05-01T00:00:00Z")
    site = create_site(insurer_id="FM-1")
    incident = create_incident(site["id"], occurred_at="2026-05-01T00:00:00Z",
                               investigation_lead_id="inv-1")
    capa = create_capa(site["id"], incident["id"], owner_id="inv-1",
                       due_at="2026-05-02T00:00:00Z")

    set_clock("2026-05-03T00:00:00Z")

    after = validate_success(api.get_incident(site["id"], incident["id"],
                                              ENGINEER), 200)
    assert after["capa_open_count"] == 1

    actions, meta = validate_paginated(
        api.list_capa_actions(site["id"], incident["id"], INVESTIGATOR))
    assert meta["total_count"] == 1
    assert actions[0]["id"] == capa["id"]
    assert actions[0]["status"] == "OVERDUE"


def test_incident_close_blocked_by_open_capa(api):
    """PRD §3.9: "A `ComplianceManager` closes the incident (`CAPA_DEFINED →
    CLOSED`) once every CAPA action is closed: the transition requires
    `capa_open_count` to equal zero (else `ERR_CAPA_OPEN`, HTTP 422)."

    Design: Corner/errors/err_capa_open_blocks_incident_close
    """
    site = create_site(insurer_id="FM-1")
    incident = create_incident(site["id"], occurred_at="2026-05-01T00:00:00Z",
                               investigation_lead_id="inv-1")
    validate_success(api.start_investigation(
        site["id"], incident["id"],
        make_incident_investigator_headers("inv-1")), 200)
    create_capa(site["id"], incident["id"], owner_id="inv-1",
                due_at="2026-06-01T00:00:00Z")
    defined = validate_success(api.define_capa(
        site["id"], incident["id"],
        make_incident_investigator_headers("inv-1")), 200)
    assert defined["status"] == "CAPA_DEFINED"
    assert defined["capa_open_count"] == 1

    res = api.close_incident(site["id"], incident["id"], MANAGER)
    validate_error(res, ApiErrorId.ERR_CAPA_OPEN)


def test_incident_reopen_resume_investigation(api):
    """PRD §3.9: "A closed incident can be reopened (`CLOSED → REOPENED`) by a
    `ComplianceManager`, and the investigator can resume investigation from
    `REOPENED` (transition back to `INVESTIGATING`) provided the acting
    `X-User-ID` still equals `investigation_lead_id`."

    Design: Difficulty/non_linear_state_machine/incident_reopen_after_close
    """
    site = create_site()
    incident = create_closed_incident(site["id"], lead_id="inv-1")
    assert incident["status"] == "CLOSED"

    reopened = validate_success(api.reopen_incident(site["id"], incident["id"],
                                                    MANAGER), 200)
    assert reopened["status"] == "REOPENED"

    resumed = validate_success(api.start_investigation(
        site["id"], incident["id"],
        make_incident_investigator_headers("inv-1")), 200)
    assert resumed["status"] == "INVESTIGATING"


def test_incident_close_reopen_intermediate_states(api):
    """PRD §3.9: "A `ComplianceManager` closes the incident (`CAPA_DEFINED →
    CLOSED`) once every CAPA action is closed".
    PRD §3.9: "A closed incident can be reopened (`CLOSED → REOPENED`) by a
    `ComplianceManager`".

    The incident reaches terminal CLOSED through the full investigation
    pipeline, then lands in REOPENED.

    Design: Difficulty/non_linear_state_machine/incident_reopen_after_close
    """
    site = create_site()
    incident = create_incident(site["id"], occurred_at="2026-05-01T10:00:00Z",
                               investigation_lead_id="inv-1")
    assert incident["status"] == "OPEN"

    # Drive the full pipeline on this incident.
    lead = make_incident_investigator_headers("inv-1")
    investigating = validate_success(
        api.start_investigation(site["id"], incident["id"], lead), 200)
    assert investigating["status"] == "INVESTIGATING"

    capa = create_capa(site["id"], incident["id"], owner_id="inv-1")
    validate_success(api.start_capa_action(site["id"], incident["id"],
                                           capa["id"], lead), 200)
    validate_success(api.close_capa_action(site["id"], incident["id"],
                                           capa["id"], lead), 200)
    defined = validate_success(api.define_capa(site["id"], incident["id"],
                                               lead), 200)
    assert defined["status"] == "CAPA_DEFINED"

    closed = validate_success(api.close_incident(site["id"], incident["id"],
                                                 MANAGER), 200)
    assert closed["status"] == "CLOSED"

    reopened = validate_success(api.reopen_incident(site["id"], incident["id"],
                                                    MANAGER), 200)
    assert reopened["status"] == "REOPENED"
