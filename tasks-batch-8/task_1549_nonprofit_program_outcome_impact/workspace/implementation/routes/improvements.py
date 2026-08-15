"""Improvement actions: the continuous improvement loop."""
from flask import Blueprint, g, request

from db import db, new_entity, now_iso
from errors import ApiError
from middleware import require_roles
from response import ok_object, ok_list
from util import (
    get_body,
    req_str,
    opt_str,
    req_enum,
    get_or_404,
    page_of,
    serialize,
    touch,
)

bp = Blueprint("improvements", __name__)

ACTION_READ_ROLES = ("ProgramDirector", "EvaluationLead", "DataSteward")
OUTCOMES = ("EFFECTIVE", "INEFFECTIVE")


@bp.post("/programs/<pid>/improvement-actions")
@require_roles("EvaluationLead")
def create_action(pid):
    get_or_404(db.programs, pid)
    body = get_body()
    title = req_str(body, "title")
    description = opt_str(body, "description", "") or ""
    audit_finding_id = opt_str(body, "audit_finding_id")
    report_id = opt_str(body, "report_id")
    if audit_finding_id is not None and db.findings.get(audit_finding_id) is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Audit finding not found: {audit_finding_id}")
    if report_id is not None and db.reports.get(report_id) is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Report not found: {report_id}")
    ent = new_entity(
        db.actions,
        {
            "program_id": pid,
            "audit_finding_id": audit_finding_id,
            "report_id": report_id,
            "title": title,
            "description": description,
            "status": "PROPOSED",
            "effectiveness_reviewed_at": None,
            # Recorded for the segregation-of-duties check on approve.
            "_creator_id": g.user_id,
        },
    )
    return ok_object(serialize(ent), 201)


@bp.get("/programs/<pid>/improvement-actions")
@require_roles(*ACTION_READ_ROLES)
def list_program_actions(pid):
    get_or_404(db.programs, pid)
    items = [a for a in db.actions.values() if a["program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


@bp.get("/improvement-actions/<aid>")
@require_roles(*ACTION_READ_ROLES)
def get_action(aid):
    return ok_object(serialize(get_or_404(db.actions, aid)))


@bp.get("/improvement-actions")
@require_roles(*ACTION_READ_ROLES)
def list_actions():
    items = list(db.actions.values())
    for param in ("program_id", "audit_finding_id", "report_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[param] == v]
    data, limit, offset, total = page_of(items)
    return ok_list(data, limit, offset, total)


def _action_transition(aid, allowed_from, to):
    action = get_or_404(db.actions, aid)
    get_body()
    if action["status"] not in allowed_from:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Improvement action in state {action['status']} cannot transition to {to}.",
        )
    return action


@bp.post("/improvement-actions/<aid>/approve")
@require_roles("ProgramDirector")
def approve_action(aid):
    action = _action_transition(aid, ("PROPOSED",), "APPROVED")
    # Segregation of duties: the proposer cannot approve their own action.
    if g.user_id == action["_creator_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTY", 422, "The proposer cannot approve their own action."
        )
    action["status"] = "APPROVED"
    touch(db.actions, action)
    return ok_object(serialize(action))


@bp.post("/improvement-actions/<aid>/start")
@require_roles("EvaluationLead")
def start_action(aid):
    action = _action_transition(aid, ("APPROVED",), "IN_PROGRESS")
    action["status"] = "IN_PROGRESS"
    touch(db.actions, action)
    return ok_object(serialize(action))


@bp.post("/improvement-actions/<aid>/implement")
@require_roles("EvaluationLead")
def implement_action(aid):
    action = _action_transition(aid, ("IN_PROGRESS",), "IMPLEMENTED")
    action["status"] = "IMPLEMENTED"
    touch(db.actions, action)
    return ok_object(serialize(action))


@bp.post("/improvement-actions/<aid>/verify")
@require_roles("ProgramDirector")
def verify_action(aid):
    action = get_or_404(db.actions, aid)
    body = get_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    if action["status"] != "IMPLEMENTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            f"Improvement action in state {action['status']} cannot be verified.",
        )
    action["status"] = (
        "VERIFIED_EFFECTIVE" if outcome == "EFFECTIVE" else "VERIFIED_INEFFECTIVE"
    )
    action["effectiveness_reviewed_at"] = now_iso()
    touch(db.actions, action)
    return ok_object(serialize(action))


@bp.post("/improvement-actions/<aid>/reopen")
@require_roles("EvaluationLead")
def reopen_action(aid):
    action = _action_transition(aid, ("VERIFIED_INEFFECTIVE",), "PROPOSED")
    action["status"] = "PROPOSED"
    touch(db.actions, action)
    return ok_object(serialize(action))
