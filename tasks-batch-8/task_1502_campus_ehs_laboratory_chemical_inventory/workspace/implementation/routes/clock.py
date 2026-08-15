"""Test-driving logical clock endpoint (PRD §2.5)."""
from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import get_actor, require_role
from response import success_object
from services.common import get_body, require_fields
from services.training import expiry_sweep

bp = Blueprint("clock", __name__)


@bp.post("/ehs/_clock/set_current_utc")
def set_clock():
    _, role = get_actor()
    body = get_body()
    require_role(role, ("EHSAdmin",))
    require_fields(body, ["to_iso8601"])
    target = db.parse_iso(body.get("to_iso8601"))
    if target is None:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 datetime", 400)
    db.set_now(target)
    # Sweep side effects: expire overdue ASSIGNED training, re-evaluate
    # accumulation overstay, recompute every lab's posture.
    expiry_sweep()
    return success_object({"current_utc": db.iso(db.now())})
