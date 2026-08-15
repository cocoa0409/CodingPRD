"""Logical clock test-driving endpoint (PRD §2.5)."""
from flask import Blueprint

import db
import validation as v
from middleware import ANY_ROLES, get_context, require_roles
from response import ok

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    get_context()
    require_roles(ANY_ROLES)
    body = v.get_body()
    target = v.req_datetime(body, "to_iso8601")
    db.set_clock(target)
    # Furnace postures recompute lazily on the next furnace read / release / start-run.
    return ok({})
