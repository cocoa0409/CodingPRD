"""Top-level add-on line reads (PRD §4)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
import helpers
from services.serialize import addon_line_out

bp = Blueprint("addon_lines", __name__)


@bp.route("/add-on-lines/<line_id>", methods=["GET"])
def get_addon_line(line_id):
    _, role = authenticate()
    require_role(role, {"OperationsManager", "PlatformAdmin", "Customer"})
    rec = db.booking_add_ons.get(line_id)
    if not rec:
        raise err(errors.ERR_NOT_FOUND, "Add-on line not found.")
    return success(addon_line_out(rec), 200)


@bp.route("/add-on-lines", methods=["GET"])
def list_addon_lines():
    _, role = authenticate()
    require_role(role, {"OperationsManager", "PlatformAdmin"})
    limit, offset = helpers.pagination_params()
    recs = list(db.booking_add_ons.values())
    add_on_id = request.args.get("add_on_id")
    if add_on_id is not None:
        recs = [r for r in recs if r["add_on_id"] == add_on_id]
    window, total = helpers.paginate(recs, limit, offset)
    return list_response([addon_line_out(r) for r in window], limit, offset, total)
