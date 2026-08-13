from flask import Blueprint

from db import store
from middleware import require_roles
from response import success
from services import get_body, parse_dt, iso
from errors import ApiError

bp = Blueprint("clock", __name__)


@bp.post("/peer-review/_clock/set_current_utc")
def set_current_utc():
    require_roles("QualityDirector")
    b = get_body()
    raw = b.get("to_iso8601")
    if raw is None:
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 is required")
    dt = parse_dt(raw, "to_iso8601")
    store.clock = dt  # second-precision logical clock
    return success({"current_utc": iso(store.clock)})
