"""Incident lifecycle: open, activate, privilege dimension, resolve, sla-sweep.

Endpoints in this module (8):
  POST   /crisis/incidents
  GET    /crisis/incidents/{incident_id}
  GET    /crisis/incidents
  POST   /crisis/incidents/{incident_id}/activate
  POST   /crisis/incidents/{incident_id}/assert-privilege
  POST   /crisis/incidents/{incident_id}/waive-privilege
  POST   /crisis/incidents/{incident_id}/resolve
  POST   /crisis/incidents/{incident_id}/sla-sweep
"""

from flask import Blueprint

import logic as L
from core import (
    ALL_ROLES,
    D,
    Field,
    authenticate,
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

bp = Blueprint("incident", __name__)


def blank_incident(title, scenario_code, created_by, reputation_index_before):
    return new_record(
        {
            "title": title,
            "scenario_code": scenario_code,
            "created_by_member_id": created_by,
            "reputation_index_before": reputation_index_before,
            "reputation_index_after": None,
            "response_state": "MONITORING",
            "privilege_state": "NON_PRIVILEGED",
            "legal_hold_active": False,
            "privilege_basis": None,
            "comms_posture": "OPEN",
            "activated_at": None,
            "resolved_at": None,
            "severity_tier": None,
            "severity_basis": None,
            "severity_score": None,
            "final_severity_tier": None,
            "final_severity_score": None,
            "holding_statement_due_at": None,
            "holding_statement_published_at": None,
            "sla_breached": False,
            "base_containment_score": None,
            "amplification_rate_applied": None,
            "containment_priority_score": None,
            "stakeholder_reach_index": D("0.00"),
            "linked_signal_count": 0,
            "escalated_signal_count": 0,
            "open_approval_task_count": 0,
            "blocked_notice_count": 0,
            "released_notice_count": 0,
            "open_claim_count": 0,
            "confirmed_interview_count": 0,
            "reputation_delta_reported": None,
        }
    )


@bp.post("/crisis/incidents")
def create_incident():
    caller = authenticate(("IncidentLead",))
    body = validate_body(
        [
            Field("title", "string", required=True, max_len=160),
            Field("scenario_code", "enum", required=True, values=L.SCENARIO_CODES),
            Field(
                "reputation_index_before",
                "number",
                default=D("50.00"),
                min="0.00",
                max="100.00",
                places=2,
            ),
        ]
    )
    incident = blank_incident(
        body["title"],
        body["scenario_code"],
        caller.user_id,
        body["reputation_index_before"],
    )
    store.incidents[incident["id"]] = incident
    return ok(incident, 201)


@bp.get("/crisis/incidents/<incident_id>")
def read_incident(incident_id):
    authenticate(ALL_ROLES)
    return ok(L.get_incident(incident_id))


@bp.get("/crisis/incidents")
def list_incidents():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    response_state = enum_filter("response_state", L.RESPONSE_STATES)
    privilege_state = enum_filter("privilege_state", L.PRIVILEGE_STATES)
    posture = enum_filter("comms_posture", L.POSTURES)
    tier = enum_filter("severity_tier", L.SEVERITY_TIERS)
    creator = str_filter("created_by_member_id")
    rows = list(store.incidents.values())
    if response_state is not None:
        rows = [r for r in rows if r["response_state"] == response_state]
    if privilege_state is not None:
        rows = [r for r in rows if r["privilege_state"] == privilege_state]
    if posture is not None:
        rows = [r for r in rows if r["comms_posture"] == posture]
    if tier is not None:
        rows = [r for r in rows if r["severity_tier"] == tier]
    if creator is not None:
        rows = [r for r in rows if r["created_by_member_id"] == creator]
    window, total = paged(rows, limit, offset)
    return ok_list(window, limit, offset, total)


# ---------------------------------------------------------------------------
# Activation (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.post("/crisis/incidents/<incident_id>/activate")
def activate(incident_id):
    authenticate(("IncidentLead",))
    validate_body([])
    incident = L.get_incident(incident_id)
    # 10/11. from-state on the response dimension.
    if incident["response_state"] != "MONITORING":
        fail(
            "ERR_INCIDENT_ALREADY_RESOLVED",
            "Only a MONITORING incident may be activated.",
        )
    # 12. posture gate.
    L.require_not_frozen(incident)
    # 15. the incident-lead seat must be acknowledged.
    if L.acknowledged_seat(incident["id"], "INCIDENT_LEAD") is None:
        fail(
            "ERR_ASSIGNMENT_NOT_ACKNOWLEDGED",
            "An ACKNOWLEDGED INCIDENT_LEAD seat is required to activate.",
        )
    # 24. at least one escalated signal.
    L.recompute_counts(incident)
    if incident["escalated_signal_count"] < 1:
        fail("ERR_NO_ESCALATED_SIGNAL", "The incident has no ESCALATED signal.")
    tier, score = L.provisional_severity(incident)
    # 15 (second form). SEV1 additionally requires counsel in the room.
    if tier == "SEV1" and L.acknowledged_seat(incident["id"], "LEGAL_COUNSEL") is None:
        fail(
            "ERR_ASSIGNMENT_NOT_ACKNOWLEDGED",
            "A SEV1 activation requires an ACKNOWLEDGED LEGAL_COUNSEL seat.",
        )
    incident["response_state"] = "ACTIVATED"
    incident["activated_at"] = store.now()
    incident["severity_tier"] = tier
    incident["severity_score"] = score
    incident["severity_basis"] = "PROVISIONAL"
    incident["holding_statement_due_at"] = L.holding_statement_due_at(incident)
    L.recompute_containment(incident)
    L.refresh(incident)
    touch(incident)
    return ok(incident)


# ---------------------------------------------------------------------------
# Privilege dimension (PRD 3.4)
# ---------------------------------------------------------------------------
@bp.post("/crisis/incidents/<incident_id>/assert-privilege")
def assert_privilege(incident_id):
    caller = authenticate(("LegalCounsel",))
    body = validate_body([Field("privilege_basis", "string", required=True)])
    incident = L.get_incident(incident_id)
    # 11. the response dimension must not have reached RESOLVED.
    L.require_not_resolved(incident)
    # 12. gate. An already-asserted incident is FROZEN and assertion is not one
    # of the three FROZEN exemptions, so the posture error is the declared 409.
    if incident["privilege_state"] != "NON_PRIVILEGED" or incident["comms_posture"] == "FROZEN":
        fail(
            "ERR_COMMS_POSTURE_FROZEN",
            "Privilege may only be asserted from NON_PRIVILEGED with an unfrozen posture.",
        )
    # 13. privilege circle.
    L.require_privilege(caller)
    # 15. the acting counsel must hold an acknowledged LEGAL_COUNSEL seat here.
    if L.acknowledged_seat(incident["id"], "LEGAL_COUNSEL", caller.user_id) is None:
        fail(
            "ERR_ASSIGNMENT_NOT_ACKNOWLEDGED",
            "The acting counsel holds no ACKNOWLEDGED LEGAL_COUNSEL seat on this incident.",
        )
    incident["privilege_state"] = "PRIVILEGED_ASSERTED"
    incident["legal_hold_active"] = True
    incident["privilege_basis"] = body["privilege_basis"]
    now = store.now()
    # HOP 1: void PENDING tasks whose assignee sits outside the circle.
    statement_ids = {s["id"] for s in L.incident_statements(incident["id"])}
    touched_statements = set()
    for task in sorted(store.tasks.values(), key=lambda t: t["_seq"]):
        if task["statement_id"] not in statement_ids or task["state"] != "PENDING":
            continue
        assignee = store.members.get(task["assignee_member_id"])
        if assignee is not None and assignee["privilege_cleared"]:
            continue
        task["state"] = "VOIDED"
        task["decided_at"] = now
        touch(task)
        touched_statements.add(task["statement_id"])
    # HOP 3: statements stripped of every outstanding task fall back to revision.
    for statement_id in sorted(touched_statements):
        statement = store.statements[statement_id]
        if statement["state"] != "IN_REVIEW":
            continue
        remaining = [t for t in L.round_tasks(statement) if t["state"] == "PENDING"]
        approved = [t for t in L.round_tasks(statement) if t["state"] == "APPROVED"]
        if not remaining and len(approved) < statement["quorum_required"]:
            L.push_revision_requested(statement, incident)
    # HOP 2 + posture.
    L.refresh(incident)
    touch(incident)
    return ok(incident)


@bp.post("/crisis/incidents/<incident_id>/waive-privilege")
def waive_privilege(incident_id):
    caller = authenticate(("LegalCounsel",))
    validate_body([Field("waiver_reason", "string", required=True)])
    incident = L.get_incident(incident_id)
    # Waiver is exempt from the FROZEN gate, otherwise a hold could never lift.
    if incident["privilege_state"] != "PRIVILEGED_ASSERTED":
        fail(
            "ERR_COMMS_POSTURE_FROZEN",
            "Privilege may only be waived from PRIVILEGED_ASSERTED.",
        )
    L.require_privilege(caller)
    incident["privilege_state"] = "PRIVILEGE_WAIVED"
    incident["legal_hold_active"] = False
    L.refresh(incident)
    touch(incident)
    return ok(incident)


# ---------------------------------------------------------------------------
# Resolution (PRD 3.9)
# ---------------------------------------------------------------------------
@bp.post("/crisis/incidents/<incident_id>/resolve")
def resolve(incident_id):
    authenticate(("IncidentLead",))
    body = validate_body(
        [
            Field(
                "reputation_index_after",
                "number",
                required=True,
                min="0.00",
                max="100.00",
                places=2,
            )
        ]
    )
    incident = L.get_incident(incident_id)
    L.require_activated(incident)
    L.recompute_counts(incident)
    if any(n["state"] in ("QUEUED", "BLOCKED") for n in L.incident_notices(incident["id"])):
        fail(
            "ERR_OPEN_NOTICES_BLOCK_RESOLUTION",
            "Stakeholder notices are still QUEUED or BLOCKED.",
        )
    if incident["open_claim_count"] != 0:
        fail("ERR_OPEN_CLAIMS_BLOCK_RESOLUTION", "Misinformation claims are still open.")
    now = store.now()
    incident["reputation_index_after"] = body["reputation_index_after"]
    incident["resolved_at"] = now
    incident["response_state"] = "RESOLVED"
    tier, score = L.final_severity(incident)
    incident["final_severity_tier"] = tier
    incident["final_severity_score"] = score
    incident["severity_basis"] = "FINAL"

    claims = L.incident_claims(incident["id"])
    review = new_record(
        {
            "incident_id": incident["id"],
            "reputation_index_before": incident["reputation_index_before"],
            "reputation_index_after": incident["reputation_index_after"],
            "exposure_factor": L.exposure_factor_for(incident),
            "total_claim_count": len(claims),
            "corrected_claim_count": sum(1 for c in claims if c["corrected"]),
            "reputation_delta_raw": None,
            "reputation_delta_adjusted": None,
            "scoring_method": None,
            "reported_delta": None,
            "playbook_update_count": 0,
            "state": "OPEN",
            "scored_at": None,
        }
    )
    store.reviews[review["id"]] = review

    # HOP 1: stand the team down.
    spokesperson_ids = set()
    affected_members = set()
    for assignment in sorted(L.incident_assignments(incident["id"]), key=lambda a: a["_seq"]):
        if assignment["state"] != "ACKNOWLEDGED":
            continue
        assignment["state"] = "STOOD_DOWN"
        assignment["stood_down_at"] = now
        touch(assignment)
        affected_members.add(assignment["member_id"])
        if assignment["team_role"] == "SPOKESPERSON":
            spokesperson_ids.add(assignment["member_id"])
    # HOP 2: cancel that spokesperson's bookings on this incident.
    for interview in sorted(L.incident_interviews(incident["id"]), key=lambda i: i["_seq"]):
        if interview["spokesperson_member_id"] not in spokesperson_ids:
            continue
        if interview["state"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        interview["state"] = "CANCELLED"
        interview["cancel_reason"] = "AUTO_CASCADE_INCIDENT_RESOLVED"
        touch(interview)
        affected_members.add(interview["spokesperson_member_id"])
    # HOP 3: release the spokesperson-load ledger and refresh member counters.
    for member_id in sorted(affected_members):
        member = store.members.get(member_id)
        if member is None:
            continue
        L.bump_member(
            member,
            lambda m: (
                L.recompute_scheduled_interview_minutes(m),
                L.recompute_active_assignment_count(m),
            ),
        )
    L.refresh(incident)
    touch(incident)
    return ok(incident)


# ---------------------------------------------------------------------------
# Operator checkpoint (PRD 3.3) - exempt from the FROZEN gate
# ---------------------------------------------------------------------------
@bp.post("/crisis/incidents/<incident_id>/sla-sweep")
def sla_sweep(incident_id):
    authenticate(("ProgramAdmin", "IncidentLead", "CommsLead"))
    validate_body([])
    incident = L.get_incident(incident_id)
    now = store.now()
    # 1. Latch the holding-statement breach.
    L.evaluate_sla_breach(incident)
    # 2. Expire approval tasks that outran their review deadline.
    statements = sorted(L.incident_statements(incident["id"]), key=lambda s: s["_seq"])
    for statement in statements:
        if statement["state"] != "IN_REVIEW" or statement["review_deadline_at"] is None:
            continue
        if not now > statement["review_deadline_at"]:
            continue
        expired = False
        # Every PENDING task on the round has outrun the same review deadline, so
        # every one of them advances PENDING -> EXPIRED (PRD 3.3 "It expires
        # approval tasks that have outrun their review deadline").
        for task in sorted(L.round_tasks(statement), key=lambda t: t["_seq"]):
            if task["state"] != "PENDING":
                continue
            task["state"] = "EXPIRED"
            task["decided_at"] = now
            touch(task)
            expired = True
        if expired:
            L.push_revision_requested(statement, incident)
    # 3. Re-score prepared material filed under this incident's scenario.
    for material in sorted(store.materials.values(), key=lambda m: m["_seq"]):
        if material["scenario_code"] != incident["scenario_code"]:
            continue
        if material["readiness_state"] not in ("READY", "STALE"):
            continue
        score, state = L.material_readiness(material, now)
        if score != material["readiness_score"] or state != material["readiness_state"]:
            material["readiness_score"] = score
            material["readiness_state"] = state
            touch(material)
    # 4. Recompute the posture and bump the incident.
    L.refresh(incident)
    touch(incident)
    return ok(incident)
