from flask import Blueprint

import store
from common import ApiError, authorize, ok_object, get_body, require_iso

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    uid, role = authorize(["PlatformAdmin"])
    body = get_body()
    target = require_iso(body, "to_iso8601")
    if target < store.clock_now():
        raise ApiError("ERR_CLOCK_BEFORE_CURRENT", "target is before the current clock")
    store.set_clock(target)
    return ok_object({"current_utc": store.fmt_dt(target)})
