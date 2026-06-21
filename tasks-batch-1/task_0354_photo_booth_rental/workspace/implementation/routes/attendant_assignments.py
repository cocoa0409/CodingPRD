"""Top-level attendant assignment reads (PRD §4)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
import helpers
from services.serialize import plain_out

bp = Blueprint("attendant_assignments", __name__)


@bp.route("/attendant-assignments/<assign_id>", methods=["GET"])
def get_assignment(assign_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager", "PlatformAdmin"})
    rec = db.attendant_assignments.get(assign_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Attendant assignment not found.")
    return success(plain_out(rec), 200)


@bp.route("/attendant-assignments", methods=["GET"])
def list_assignments():
    _, role = authenticate()
    require_role(role, {"OperationsManager", "PlatformAdmin"})
    limit, offset = helpers.pagination_params()
    recs = list(db.attendant_assignments.values())
    attendant_id = request.args.get("attendant_id")
    if attendant_id is not None:
        recs = [r for r in recs if r.get("attendant_id") == attendant_id]
    window, total = helpers.paginate(recs, limit, offset)
    return list_response([plain_out(r) for r in window], limit, offset, total)
