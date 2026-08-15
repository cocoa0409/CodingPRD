"""Logical clock endpoint (PRD section 2.5)."""

from flask import Blueprint

import db
from middleware import authenticate, require_role
from response import success
from util import as_dt, body, fmt_dt

bp = Blueprint("clock", __name__)


@bp.route("/plant/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    data = body()
    to_iso8601 = as_dt(data.get("to_iso8601"), "to_iso8601", required=True)
    db.set_clock(to_iso8601)
    return success({"current_utc": fmt_dt(db.get_clock())})
