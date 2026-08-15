"""Logical clock (PRD 2.5)."""
from flask import Blueprint

import db
from middleware import require_role
from response import success
from util import get_body, v_dt

bp = Blueprint("clock", __name__)


@bp.post("/haul/_clock/set_current_utc")
def set_clock():
    require_role("CarrierAdmin")
    body = get_body()
    raw = body.get("to_iso8601")
    dt = v_dt(body, "to_iso8601")
    db.clock["dt"] = dt
    db.clock["raw"] = raw
    return success({"current_utc": db.clock["raw"]})
