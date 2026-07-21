"""Administrative logical clock (PRD §2.8)."""
from flask import Blueprint

import store
import api as h
from errors import ApiError

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    h.require_role("StoreManager")
    body = h.get_body()
    h.require_fields(body, ["to_iso8601"])
    dt = store.parse_dt(body["to_iso8601"])
    if dt is None:
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be an ISO-8601 instant")
    store.set_clock(dt)
    return h.success({"current_utc": store.iso(dt)})
