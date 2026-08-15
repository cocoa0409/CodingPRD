"""Logical clock test-driving endpoint (SystemAdmin only)."""
from flask import Blueprint

import shape
from envelope import ok_object
from security import authenticate, require_role
from store import STORE, iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = shape.get_body()
    target = shape.req_iso_datetime(body, "to_iso8601")
    ctx = authenticate()
    require_role(ctx, ["SystemAdmin"])
    STORE.clock = target
    return ok_object({"current_utc": iso(STORE.clock)})
