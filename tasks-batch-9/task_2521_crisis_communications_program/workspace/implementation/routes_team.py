"""Crisis-team seats (PRD 3.3) and issue signals (PRD 3.2).

Endpoints in this module (9):
  POST   /crisis/team-assignments
  GET    /crisis/team-assignments/{assignment_id}
  GET    /crisis/team-assignments
  POST   /crisis/team-assignments/{assignment_id}/acknowledge
  POST   /crisis/issue-signals
  GET    /crisis/issue-signals/{signal_id}
  GET    /crisis/issue-signals
  POST   /crisis/issue-signals/{signal_id}/link
  POST   /crisis/issue-signals/{signal_id}/escalate
"""

from flask import Blueprint

import logic as L
from core import (
    ALL_ROLES,
    D,
    Field,
    authenticate,
    bool_filter,
    enum_filter,
    fail,
    new_record,
    ok,
    ok_list,
    pagination,
    paged,
    store,
    str_filter,
    touch,
    validate_body,
)

bp = Blueprint("team", __name__)


# ---------------------------------------------------------------------------
# TeamAssignment
# ---------------------------------------------------------------------------
@bp.post("/crisis/team-assignments")
def create_assignment():
    authenticate(("IncidentLead",))
    body = validate_body(
        [
            Field("incident_id", "id", required=True),
            Field("member_id", "id", required=True),
            Field("team_role", "enum", required=True, values=L.TEAM_ROLES),
            Field("decision_authority", "enum", required=True, values=L.DECISION_AUTHORITIES),
        ]
    )
    # 6. body foreign keys resolve in the order declared by PRD 2.5.
    incident = L.get_incident(body["incident_id"])
    member = L.get_member(body["member_id"])
    # 11. seating is refused once the response has been resolved.
    L.require_not_resolved(incident)
    # 12. posture gate.
    L.require_not_frozen(incident)
    # 19. one live seat per team_role per incident.
    for existing in L.incident_assignments(incident["id"]):
        if existing["team_role"] == body["team_role"] and existing["state"] in (
            "ASSIGNED",
            "ACKNOWLEDGED",
        ):
            fail(
                "ERR_DUPLICATE_ASSIGNMENT_ROLE",
                "Another live seat on this incident already holds %s." % body["team_role"],
            )
    assignment = new_record(
        {
            "incident_id": incident["id"],
            "member_id": member["id"],
            "team_role": body["team_role"],
            "decision_authority": body["decision_authority"],
            "state": "ASSIGNED",
            "acknowledged_at": None,
            "stood_down_at": None,
        }
    )
    store.assignments[assignment["id"]] = assignment
    L.bump_member(member, L.recompute_active_assignment_count)
    return ok(assignment, 201)


@bp.get("/crisis/team-assignments/<assignment_id>")
def read_assignment(assignment_id):
    authenticate(ALL_ROLES)
    return ok(L.get_assignment(assignment_id))


@bp.get("/crisis/team-assignments")
def list_assignments():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    incident_id = str_filter("incident_id")
    member_id = str_filter("member_id")
    team_role = enum_filter("team_role", L.TEAM_ROLES)
    state = enum_filter("state", ("ASSIGNED", "ACKNOWLEDGED", "STOOD_DOWN"))
    rows = list(store.assignments.values())
    if incident_id is not None:
        rows = [r for r in rows if r["incident_id"] == incident_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if team_role is not None:
        rows = [r for r in rows if r["team_role"] == team_role]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/crisis/team-assignments/<assignment_id>/acknowledge")
def acknowledge_assignment(assignment_id):
    caller = authenticate(
        ("IncidentLead", "LegalCounsel", "CommsLead", "Spokesperson", "SocialListener", "ExecSponsor")
    )
    validate_body([])
    assignment = L.get_assignment(assignment_id)
    # 7. ownership binding: only the seated member may accept the seat.
    if caller.user_id != assignment["member_id"]:
        fail("ERR_ROLE_NOT_PERMITTED", "Only the seated member may acknowledge this seat.")
    # 10. from-state.
    if assignment["state"] != "ASSIGNED":
        fail("ERR_ASSIGNMENT_STATE_INVALID", "Only an ASSIGNED seat may be acknowledged.")
    incident = store.incidents.get(assignment["incident_id"])
    if incident is not None:
        # 11. and 12.
        L.require_not_resolved(incident)
        L.require_not_frozen(incident)
    assignment["state"] = "ACKNOWLEDGED"
    assignment["acknowledged_at"] = store.now()
    touch(assignment)
    member = store.members.get(assignment["member_id"])
    if member is not None:
        L.bump_member(member, L.recompute_active_assignment_count)
    return ok(assignment)


# ---------------------------------------------------------------------------
# IssueSignal
# ---------------------------------------------------------------------------
@bp.post("/crisis/issue-signals")
def create_signal():
    authenticate(("SocialListener", "ProgramAdmin"))
    body = validate_body(
        [
            Field("channel_id", "id", required=True),
            Field("headline", "string", required=True, max_len=240),
            Field("reach_score", "int", required=True, min=0, max=100),
            Field("sentiment_score", "number", required=True, min="-1.0", max="1.0"),
            Field("source_credibility_tier", "enum", required=True, values=L.CREDIBILITY_TIERS),
            Field("regulatory_flag", "bool", default=False),
            Field("incident_id", "id", default=None, nullable=True),
        ]
    )
    # 6. incident_id resolves before channel_id (PRD 2.5 ordering).
    incident = None
    if body["incident_id"] is not None:
        incident = L.get_incident(body["incident_id"])
    channel = L.get_channel(body["channel_id"])
    score = L.signal_escalation_score(
        body["reach_score"],
        body["sentiment_score"],
        body["source_credibility_tier"],
        channel["channel_type"],
        body["regulatory_flag"],
    )
    signal = new_record(
        {
            "channel_id": channel["id"],
            "incident_id": incident["id"] if incident else None,
            "headline": body["headline"],
            "reach_score": body["reach_score"],
            "sentiment_score": body["sentiment_score"],
            "source_credibility_tier": body["source_credibility_tier"],
            "regulatory_flag": body["regulatory_flag"],
            "escalation_score": score,
            "detected_at": store.now(),
            "state": "LINKED" if incident else "OPEN",
            "escalated_at": None,
        }
    )
    store.signals[signal["id"]] = signal
    if incident is not None:
        L.refresh(incident)
    return ok(signal, 201)


@bp.get("/crisis/issue-signals/<signal_id>")
def read_signal(signal_id):
    authenticate(ALL_ROLES)
    return ok(L.get_signal(signal_id))


@bp.get("/crisis/issue-signals")
def list_signals():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    incident_id = str_filter("incident_id")
    channel_id = str_filter("channel_id")
    state = enum_filter("state", ("OPEN", "LINKED", "ESCALATED"))
    rows = list(store.signals.values())
    if incident_id is not None:
        rows = [r for r in rows if r["incident_id"] == incident_id]
    if channel_id is not None:
        rows = [r for r in rows if r["channel_id"] == channel_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/crisis/issue-signals/<signal_id>/link")
def link_signal(signal_id):
    authenticate(("SocialListener", "IncidentLead"))
    body = validate_body([Field("incident_id", "id", required=True)])
    signal = L.get_signal(signal_id)
    incident = L.get_incident(body["incident_id"])
    # 10. from-state.
    if signal["state"] != "OPEN":
        fail("ERR_INVALID_SIGNAL_STATE", "Only an OPEN signal may be linked.")
    # 11. and 12.
    L.require_not_resolved(incident)
    L.require_not_frozen(incident)
    signal["incident_id"] = incident["id"]
    signal["state"] = "LINKED"
    touch(signal)
    L.refresh(incident)
    touch(incident)
    return ok(signal)


@bp.post("/crisis/issue-signals/<signal_id>/escalate")
def escalate_signal(signal_id):
    authenticate(("SocialListener", "IncidentLead"))
    validate_body([])
    signal = L.get_signal(signal_id)
    # 10. an unlinked signal can never be escalated.
    if signal["state"] != "LINKED":
        fail("ERR_INVALID_SIGNAL_STATE", "Only a LINKED signal may be escalated.")
    incident = store.incidents.get(signal["incident_id"])
    if incident is None:
        fail("ERR_INCIDENT_NOT_FOUND", "The signal's incident no longer resolves.")
    # 12. posture gate.
    L.require_not_frozen(incident)
    # 23. the frozen escalation score must clear the threshold.
    if D(signal["escalation_score"]) < L.ESCALATION_THRESHOLD:
        fail(
            "ERR_ESCALATION_THRESHOLD_NOT_MET",
            "The signal's escalation_score is below 70.00.",
        )
    signal["state"] = "ESCALATED"
    signal["escalated_at"] = store.now()
    touch(signal)
    # Four-hop cascade (PRD 3.3).
    if incident["response_state"] == "ACTIVATED":
        tier, score = L.provisional_severity(incident)
        incident["severity_tier"] = tier
        incident["severity_score"] = score
        incident["severity_basis"] = "PROVISIONAL"
        incident["holding_statement_due_at"] = L.holding_statement_due_at(incident)
        L.evaluate_sla_breach(incident)
    L.recompute_containment(incident)
    L.refresh(incident)
    touch(incident)
    return ok(signal)
