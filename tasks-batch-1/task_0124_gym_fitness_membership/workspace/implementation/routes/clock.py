"""Administrative clock + delinquency sweep (PRD §2.11, §3.4)."""
from flask import Blueprint, request

import db
from middleware import authenticate, require_role
from response import success
from services import member_ops
from util import parse_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601") if isinstance(body, dict) else None
    dt = parse_dt(to_iso, "to_iso8601")
    db.store.clock = dt
    # Setting the clock alone runs no entity transitions (PRD §2.11).
    return success({}, status=200)


@bp.route("/_clock/advance_dues", methods=["POST"])
def advance_dues():
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    member_ops.run_sweep()
    return success({}, status=200)
