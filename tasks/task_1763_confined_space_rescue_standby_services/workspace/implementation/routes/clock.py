"""Logical clock administration (PRD section 2.4)."""

from flask import Blueprint

import db
from helpers import body, parse_dt, reject_unknown, req_field
from middleware import require_auth
from response import success_object
from services import run_clock_sweeps

bp = Blueprint("clock", __name__)


@bp.route("/rescue-ops/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_auth(("OperationsManager",))
    data = body()
    reject_unknown(data, {"to_iso8601"})
    to_iso = req_field(data, "to_iso8601")
    parse_dt(to_iso, "to_iso8601")  # validation only; stored verbatim
    db.current_utc_iso = to_iso
    run_clock_sweeps()
    return success_object({"current_utc": to_iso}, 200)
