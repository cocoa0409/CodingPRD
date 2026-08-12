"""Logical clock + due-date sweep endpoints."""
from flask import Blueprint

from clock import parse_iso8601, set_current, to_iso, now
from middleware import require_roles, get_json_body, check_known_fields, require_fields
from response import success_object
from services.sweep import run_sweep

bp = Blueprint("clock_sweep", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles({"BiobankAdmin"})
    body = get_json_body()
    check_known_fields(body, {"to_iso8601"})
    require_fields(body, ["to_iso8601"])
    dt = parse_iso8601(body["to_iso8601"], "to_iso8601")
    set_current(dt)
    return success_object({"current_utc": to_iso(now())})


@bp.route("/biobank/sweeps/process-due", methods=["POST"])
def process_due():
    require_roles({"BiobankAdmin"})
    get_json_body()  # accept (and ignore) an empty body
    return success_object(run_sweep())
