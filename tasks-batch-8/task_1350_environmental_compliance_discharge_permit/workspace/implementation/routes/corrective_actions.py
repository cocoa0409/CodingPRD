"""CorrectiveAction endpoints."""

from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_CORRECTIVE_ACTION_NOT_FOUND,
    ERR_CORRECTIVE_ACTION_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields
from services.core import (
    touch,
    append_audit,
    serialize_corrective_action,
    paginate,
    recompute_permit_rollup,
    permit_for_corrective_action,
)

bp = Blueprint("corrective_actions", __name__)


@bp.route("/npdes/corrective-actions", methods=["GET"])
def list_cas():
    require_roles(["Any"])
    items = list(db.corrective_actions.values())
    for param in ("inspection_id", "exceedance_id", "status"):
        v = request.args.get(param)
        if v:
            items = [c for c in items if (c.get(param) or "") == v]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_corrective_action(c) for c in page], total, limit, offset)


@bp.route("/npdes/corrective-actions/<cid>", methods=["GET"])
def get_ca(cid):
    require_roles(["Any"])
    ca = db.corrective_actions.get(cid)
    if ca is None:
        raise err(ERR_CORRECTIVE_ACTION_NOT_FOUND, 404, "CorrectiveAction not found")
    return success(serialize_corrective_action(ca), 200)


@bp.route("/npdes/corrective-actions/<cid>/start", methods=["POST"])
def start_ca(cid):
    user_id, role = require_roles(["FacilityInspector"])
    ca = db.corrective_actions.get(cid)
    if ca is None:
        raise err(ERR_CORRECTIVE_ACTION_NOT_FOUND, 404, "CorrectiveAction not found")
    if ca["status"] not in ("OPEN", "REOPENED"):
        raise err(ERR_CORRECTIVE_ACTION_INVALID_STATE, 409, "Start requires OPEN or REOPENED")
    prev = ca["status"]
    ca["status"] = "IN_PROGRESS"
    touch(ca)
    action = "CA_RESTARTED" if prev == "REOPENED" else "CA_STARTED"
    append_audit("CorrectiveAction", ca["id"], action, user_id, role)
    return success(serialize_corrective_action(ca), 200)


@bp.route("/npdes/corrective-actions/<cid>/complete", methods=["POST"])
def complete_ca(cid):
    user_id, role = require_roles(["FacilityInspector"])
    ca = db.corrective_actions.get(cid)
    if ca is None:
        raise err(ERR_CORRECTIVE_ACTION_NOT_FOUND, 404, "CorrectiveAction not found")
    if ca["status"] != "IN_PROGRESS":
        raise err(ERR_CORRECTIVE_ACTION_INVALID_STATE, 409, "Complete requires IN_PROGRESS")
    body = get_body()
    require_fields(body, ["actual_cost_cents"])
    cost = body["actual_cost_cents"]
    if isinstance(cost, bool) or not isinstance(cost, int) or cost < 0:
        raise err(ERR_INVALID_REQUEST, 400, "actual_cost_cents must be an integer >= 0")
    ca["resolved_at"] = db.clock.now()
    ca["resolved_by_user_id"] = user_id
    ca["actual_cost_cents"] = cost
    ca["status"] = "COMPLETED"
    touch(ca)
    append_audit("CorrectiveAction", ca["id"], "CA_COMPLETED", user_id, role)
    return success(serialize_corrective_action(ca), 200)


@bp.route("/npdes/corrective-actions/<cid>/verify", methods=["POST"])
def verify_ca(cid):
    user_id, role = require_roles(["Regulator"])
    ca = db.corrective_actions.get(cid)
    if ca is None:
        raise err(ERR_CORRECTIVE_ACTION_NOT_FOUND, 404, "CorrectiveAction not found")
    if ca["status"] != "COMPLETED":
        raise err(ERR_CORRECTIVE_ACTION_INVALID_STATE, 409, "Verify requires COMPLETED")
    if user_id == ca["resolved_by_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES, 403, "Verifier must differ from resolver")
    ca["verified_by_user_id"] = user_id
    ca["status"] = "VERIFIED"
    touch(ca)
    permit = permit_for_corrective_action(ca)
    if permit is not None:
        recompute_permit_rollup(permit["id"])
    append_audit("CorrectiveAction", ca["id"], "CA_VERIFIED", user_id, role)
    return success(serialize_corrective_action(ca), 200)


@bp.route("/npdes/corrective-actions/<cid>/reopen", methods=["POST"])
def reopen_ca(cid):
    user_id, role = require_roles(["Regulator"])
    ca = db.corrective_actions.get(cid)
    if ca is None:
        raise err(ERR_CORRECTIVE_ACTION_NOT_FOUND, 404, "CorrectiveAction not found")
    if ca["status"] != "VERIFIED":
        raise err(ERR_CORRECTIVE_ACTION_INVALID_STATE, 409, "Reopen requires VERIFIED")
    body = get_body()
    if "reason" not in body or body["reason"] is None:
        raise err(ERR_INVALID_REQUEST, 400, "reason is required")
    ca["verified_by_user_id"] = None
    ca["resolved_at"] = None
    ca["resolved_by_user_id"] = None
    ca["actual_cost_cents"] = None
    ca["status"] = "REOPENED"
    touch(ca)
    permit = permit_for_corrective_action(ca)
    if permit is not None:
        recompute_permit_rollup(permit["id"])
    append_audit("CorrectiveAction", ca["id"], "CA_REOPENED", user_id, role)
    return success(serialize_corrective_action(ca), 200)


@bp.route("/npdes/corrective-actions/<cid>/close", methods=["POST"])
def close_ca(cid):
    user_id, role = require_roles(["FacilityInspector"])
    ca = db.corrective_actions.get(cid)
    if ca is None:
        raise err(ERR_CORRECTIVE_ACTION_NOT_FOUND, 404, "CorrectiveAction not found")
    if ca["status"] != "VERIFIED":
        raise err(ERR_CORRECTIVE_ACTION_INVALID_STATE, 409, "Close requires VERIFIED")
    ca["status"] = "CLOSED"
    touch(ca)
    append_audit("CorrectiveAction", ca["id"], "CA_CLOSED", user_id, role)
    return success(serialize_corrective_action(ca), 200)
