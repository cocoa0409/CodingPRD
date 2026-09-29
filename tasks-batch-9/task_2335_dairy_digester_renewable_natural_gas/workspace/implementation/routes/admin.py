from flask import Blueprint

from db import db, _parse_iso
from errors import fail
from middleware import endpoint, body
from response import ok

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_clock():
    b = body()
    raw = b.string("to_iso8601")
    dt = _parse_iso(raw)
    if dt is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant.")
    db.set_clock(dt)
    return ok({})
