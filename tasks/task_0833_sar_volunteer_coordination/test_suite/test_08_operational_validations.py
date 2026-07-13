"""Capacity, uniqueness, deployed-responder, and cross-entity readiness validations."""
from test_helpers import (
    validate_error, TEST_USERS,
    ApiErrorId,
    create_incident, create_active_incident, create_team, create_team_and_member,
    create_member, create_task, create_assigned_task, create_callout,
    create_acknowledged_callout, create_claim, create_aar,
)

COORD = TEST_USERS["coordinator_headers"]
IC = TEST_USERS["incident_commander_headers"]


def test_callout_beyond_max_responders_returns_at_capacity(api):
    """PRD §3.4: "A callout may only be created while the task has room: the number
    of non-terminal callouts on the task must be below its `max_responders`, or the
    create is rejected with `ERR_TASK_AT_CAPACITY`."

    Design: Corner/validations/callout_create_exceeds_capacity_returns_task_at_capacity
    """
    inc = create_active_incident(api, name="Cap Inc", ics_incident_number="OR-2026-1008")
    team = create_team(api)
    m_a = create_member(api, team["id"], full_name="Cap A", email="capa@x.org")
    m_b = create_member(api, team["id"], full_name="Cap B", email="capb@x.org")
    task = create_task(api, inc["id"], max_responders=1)
    create_callout(api, task["id"], m_a["id"])
    resp = api.create_callout({"task_id": task["id"], "member_id": m_b["id"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_TASK_AT_CAPACITY)


def test_second_claim_same_member_incident_returns_duplicate(api):
    """PRD §3.8: "At most one non-`REJECTED` claim may exist for any given
    member-and-incident pair; a second such claim is rejected with
    `ERR_DUPLICATE_CLAIM`."

    Design: Corner/validations/duplicate_claim_same_member_incident_returns_duplicate_claim
    """
    inc = create_incident(api, name="Dup Inc", incident_type="URBAN",
                          ics_incident_number="OR-2026-1009")
    team, member = create_team_and_member(api)
    create_claim(api, member["id"], inc["id"], declared_mileage_miles=10)
    resp = api.create_claim(
        {"member_id": member["id"], "incident_id": inc["id"], "declared_mileage_miles": 20}, COORD)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CLAIM)


def test_start_task_without_deployed_responder_rejected(api):
    """PRD §3.3: "A `Coordinator` or `IncidentCommander` starts an assigned task,
    advancing it from `ASSIGNED` to `IN_PROGRESS`, but only when at least one callout
    on the task is already `DEPLOYED`; a start with no deployed responder is rejected
    with `ERR_NO_DEPLOYED_RESPONDERS`."

    Design: Corner/validations/start_task_without_deployed_responder_returns_error
    """
    inc = create_active_incident(api, name="Start Inc", ics_incident_number="OR-2026-1010")
    task = create_assigned_task(api, inc["id"])
    resp = api.start_task(task["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_NO_DEPLOYED_RESPONDERS)


def test_close_incident_with_active_task_rejected(api):
    """PRD §3.1: "closing requires `active_task_count` to equal zero — that is, no
    task remains in `DRAFT`, `ASSIGNED`, `IN_PROGRESS`, or `SUSPENDED` — otherwise
    the close is rejected with `ERR_INCIDENT_HAS_ACTIVE_TASKS`."

    Design: Corner/validations/close_incident_with_active_task_returns_error
    """
    inc = create_active_incident(api, name="Close Inc", ics_incident_number="OR-2026-1011")
    create_task(api, inc["id"])  # remains DRAFT (active)
    api.demobilize_incident(inc["id"], IC)
    resp = api.close_incident(inc["id"], IC)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_HAS_ACTIVE_TASKS)


def test_standby_with_inactive_team_returns_team_inactive(api):
    """PRD §3.4: "A `Coordinator` or `IncidentCommander` places an acknowledged
    callout on standby, moving it from `ACKNOWLEDGED` to `STANDBY`; this requires the
    member's team to be `ACTIVE`, otherwise it is rejected with `ERR_TEAM_INACTIVE`".

    Design: Corner/validations/standby_with_inactive_team_returns_team_inactive
    """
    inc = create_active_incident(api, name="Team Inc", ics_incident_number="OR-2026-1012")
    team, member = create_team_and_member(api, team_overrides={"name": "Inactive Team"})
    task = create_task(api, inc["id"])
    co = create_acknowledged_callout(api, task["id"], member["id"])
    api.deactivate_team(team["id"], COORD)
    resp = api.standby_callout(co["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_TEAM_INACTIVE)


def test_assign_task_when_incident_planning_returns_not_active(api):
    """PRD §3.3: "Only an `IncidentCommander` may assign a task, advancing it from
    `DRAFT` to `ASSIGNED`, and only while the parent incident is `ACTIVE`; otherwise
    the assignment is rejected with `ERR_INCIDENT_NOT_ACTIVE`."

    Design: Corner/validations/assign_task_when_incident_planning_returns_not_active
    """
    inc = create_incident(api, name="Plan Inc", ics_incident_number="OR-2026-1013")
    task = create_task(api, inc["id"])
    resp = api.assign_task(task["id"], IC)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_ACTIVE)


def test_finalize_aar_when_incident_not_closed_rejected(api):
    """PRD §3.9: "An `IncidentCommander` finalizes it, moving it from `DRAFT` to
    `FINALIZED`, but only once the parent incident is `CLOSED`, else
    `ERR_INCIDENT_NOT_CLOSED`."

    Design: Corner/validations/finalize_aar_when_incident_not_closed_returns_error
    """
    inc = create_active_incident(api, name="AAR Inc", incident_type="DISASTER",
                                 ics_incident_number="OR-2026-1014")
    aar = create_aar(api, inc["id"], summary="prelim")
    resp = api.finalize_aar(aar["id"], IC)
    validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_CLOSED)
