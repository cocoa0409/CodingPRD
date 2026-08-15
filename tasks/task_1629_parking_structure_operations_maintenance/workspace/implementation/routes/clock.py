"""Logical clock test-driving endpoint (PRD 2.4)."""
from flask import Blueprint

import db
from middleware import get_actor, require_roles
from response import success_object
from services.common import body, require_datetime

bp = Blueprint("clock", __name__)


@bp.post("/ops/_clock/set_current_utc")
def set_clock():
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    payload = body()
    target = require_datetime(payload, "to_iso8601")
    db.clock.set(db.format_iso(target))
    return success_object({"current_utc": db.now_iso()})
