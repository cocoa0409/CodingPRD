"""Test-driving logical clock endpoint."""
from flask import Blueprint

from core import body, err, get_required, require_roles, success
from store import db, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PlantDirector", "ProductionPlanner", "QAManager")
def set_current_utc():
    b = body()
    to_iso = get_required(b, "to_iso8601")
    parsed = parse_dt(to_iso)
    if parsed is None:
        err("ERR_VALIDATION", 400, "to_iso8601 must be an ISO-8601 datetime")
    db.clock = parsed
    db.clock_raw = to_iso
    return success({"current_utc": db.clock_raw})
