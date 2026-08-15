from datetime import timedelta

from flask import Blueprint

import response
from db import store, touch, parse_dt
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import auth, require_role, get_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = auth()
    require_role(role, {"EngagementManager", "RecordsManager", "LegalCounsel"})
    body = get_body()
    to = body.get("to_iso8601")
    if not isinstance(to, str) or not to.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 is required")
    try:
        dt = parse_dt(to)
    except Exception:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "to_iso8601 must be a valid ISO 8601 timestamp"
        )
    store.clock = dt
    store.clock_raw = to
    # Engagement-letter validity sweep: strictly later than submitted_at + 14
    # days expires; exactly +14 days remains PENDING_ACCEPTANCE.
    for eng in store.engagements.values():
        if (
            eng["status"] == "PENDING_ACCEPTANCE"
            and dt > eng["submitted_at"] + timedelta(days=14)
        ):
            eng["status"] = "EXPIRED"
            touch(eng)
    return response.success({"current_utc": store.clock_raw})
