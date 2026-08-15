from flask import Blueprint

from db import fmt_clock, store
from middleware import require_roles
from response import ok
from util import as_datetime, body_json, req_field

bp = Blueprint("clock", __name__)


@bp.post("/fleet/_clock/set_current_utc")
@require_roles("FleetAdmin")
def set_clock():
    body = body_json()
    dt, _raw = as_datetime(req_field(body, "to_iso8601"), "to_iso8601")
    store.clock = dt
    return ok({"current_utc": fmt_clock(dt)}, "object", 200)
