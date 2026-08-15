"""Enforcement action endpoints (records are spawned by violation escalation only)."""
from flask import Blueprint, g, request

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, paginate, require_roles
from response import ok
from services import domain

bp = Blueprint("enforcement", __name__)


def get_action_or_404(action_id):
    r = db.enforcement_actions.get(action_id)
    if r is None:
        raise ApiError("ERR_ENFORCEMENT_ACTION_NOT_FOUND", "EnforcementAction id does not exist.", 404)
    return r


@bp.route("/stewardship/enforcement-actions", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_actions():
    filters = {}
    for key in ("violation_id", "easement_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    return paginate(list(db.enforcement_actions.values()), domain.enforcement_json, filters)


@bp.route("/stewardship/enforcement-actions/<enforcementActionId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_action(enforcementActionId):
    return ok(domain.enforcement_json(get_action_or_404(enforcementActionId)))


@bp.route("/stewardship/enforcement-actions/<enforcementActionId>/execute", methods=["POST"])
@require_roles("TrustBoardReviewer")
def execute_action(enforcementActionId):
    r = get_action_or_404(enforcementActionId)
    if r["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_ENFORCEMENT_STATE", "Execute requires PROPOSED.", 409)
    b = body()
    terms = b.get("agreement_terms")
    cost = b.get("remediation_cost_cents")
    if not isinstance(terms, str) or not utils.is_int(cost) or cost < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "agreement_terms and a non-negative integer remediation_cost_cents are required.",
            400,
        )
    r["agreement_terms"] = terms
    r["remediation_cost_cents"] = cost
    r["executed_by_user_id"] = g.user_id
    r["status"] = "EXECUTED"
    domain.bump(r)
    return ok(domain.enforcement_json(r))


@bp.route("/stewardship/enforcement-actions/<enforcementActionId>/complete", methods=["POST"])
@require_roles("StewardshipCoordinator")
def complete_action(enforcementActionId):
    r = get_action_or_404(enforcementActionId)
    if r["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_ENFORCEMENT_STATE", "Complete requires EXECUTED.", 409)
    if g.user_id == r["executed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "The executor may not complete the action.", 403)
    r["completed_by_user_id"] = g.user_id
    r["status"] = "COMPLETED"
    domain.bump(r)
    # Cascade: linked Violation ESCALATED -> RESOLVED.
    v = db.violations.get(r["violation_id"])
    if v is not None and v["status"] == "ESCALATED":
        v["status"] = "RESOLVED"
        v["resolved_on"] = utils.today()
        v["resolution_verified_by_user_id"] = g.user_id
        domain.bump(v)
    domain.bump(db.easements[r["easement_id"]])  # open_violation_count + posture
    return ok(domain.enforcement_json(r))


@bp.route("/stewardship/enforcement-actions/<enforcementActionId>/breach", methods=["POST"])
@require_roles("TrustBoardReviewer")
def breach_action(enforcementActionId):
    r = get_action_or_404(enforcementActionId)
    if r["status"] != "EXECUTED":
        raise ApiError("ERR_INVALID_ENFORCEMENT_STATE", "Breach requires EXECUTED.", 409)
    b = body(required=False)
    notes = b.get("breach_notes")
    if notes is not None and not isinstance(notes, str):
        raise ApiError("ERR_INVALID_REQUEST", "breach_notes must be a string.", 400)
    r["breach_notes"] = notes
    r["status"] = "BREACHED"
    domain.bump(r)
    return ok(domain.enforcement_json(r))


@bp.route("/stewardship/enforcement-actions/<enforcementActionId>/renegotiate", methods=["POST"])
@require_roles("StewardshipCoordinator")
def renegotiate_action(enforcementActionId):
    r = get_action_or_404(enforcementActionId)
    if r["status"] != "BREACHED":
        raise ApiError("ERR_INVALID_ENFORCEMENT_STATE", "Renegotiate requires BREACHED.", 409)
    b = body()
    terms = b.get("agreement_terms")
    cost = b.get("remediation_cost_cents")
    if not isinstance(terms, str) or not utils.is_int(cost) or cost < 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "agreement_terms and a non-negative integer remediation_cost_cents are required.",
            400,
        )
    r["agreement_terms"] = terms
    r["remediation_cost_cents"] = cost
    r["executed_by_user_id"] = None
    r["status"] = "PROPOSED"
    domain.bump(r)
    return ok(domain.enforcement_json(r))
