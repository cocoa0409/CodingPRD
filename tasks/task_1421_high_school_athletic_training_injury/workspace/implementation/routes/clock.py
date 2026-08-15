"""Route: logical clock (test-driving endpoint, section 2.4)."""
import db
from domain import body_json, iso_z, parse_dt, req_field, run_clock_sweep
from middleware import require_roles
from response import success_object
from flask import Blueprint

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("SystemAdmin")
def set_clock(ctx):
    body = body_json()
    target = parse_dt(req_field(body, "to_iso8601"), "to_iso8601")
    db.current_utc_iso = iso_z(target)
    run_clock_sweep()
    return success_object({"current_utc": db.current_utc_iso})
