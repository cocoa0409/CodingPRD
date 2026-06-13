"""PenaltyAppeal adjudication endpoints (PRD §3.13).

GET    /penalty-appeals/{id}
POST   /penalty-appeals/{id}/uphold   PENDING -> UPHELD (reverse points)
POST   /penalty-appeals/{id}/deny     PENDING -> DENIED (no ledger change)
"""
from flask import Blueprint

import db
import lookup
import serialize
from errors import err, ERR_INVALID_STATE
from middleware import get_user_context, require_role
from response import object_response
from services import derive, transitions

bp = Blueprint("appeals", __name__)

READ_ROLES = {"LeagueAdmin", "Assignor", "Official", "Evaluator"}


@bp.route("/penalty-appeals/<appeal_id>", methods=["GET"])
def get_appeal(appeal_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    with db.lock:
        rec = lookup.appeal(appeal_id)
        return object_response(serialize.appeal(rec))


@bp.route("/penalty-appeals/<appeal_id>/uphold", methods=["POST"])
def uphold_appeal(appeal_id):
    _, role = get_user_context()
    require_role(role, {"LeagueAdmin"})
    with db.lock:
        rec = lookup.appeal(appeal_id)
        if rec["status"] != "PENDING":
            err(ERR_INVALID_STATE, "appeal not PENDING")
        assignment = db.assignments.get(rec["assignment_id"])
        if assignment is None or assignment["status"] not in {"DECLINED", "NO_SHOW"}:
            err(ERR_INVALID_STATE, "appealed assignment no longer DECLINED/NO_SHOW")
        reversed_points = assignment.get("penalty_assessed_points", 0)
        rec["reversed_points"] = reversed_points
        rec["status"] = "UPHELD"
        db.touch(rec)
        official = db.officials.get(assignment["official_id"])
        transitions.reverse_ledger_penalty(official, reversed_points)
        # If the appealed assignment was a NO_SHOW, drop it from noshow_count
        # permanently (cascade to postseason_eligible).
        if assignment["status"] == "NO_SHOW":
            assignment["noshow_excluded"] = True
            db.touch(assignment)
        derive.recompute_official_derived(official)
        return object_response(serialize.appeal(rec))


@bp.route("/penalty-appeals/<appeal_id>/deny", methods=["POST"])
def deny_appeal(appeal_id):
    _, role = get_user_context()
    require_role(role, {"LeagueAdmin"})
    with db.lock:
        rec = lookup.appeal(appeal_id)
        if rec["status"] != "PENDING":
            err(ERR_INVALID_STATE, "appeal not PENDING")
        rec["status"] = "DENIED"
        rec["reversed_points"] = 0
        db.touch(rec)
        return object_response(serialize.appeal(rec))
