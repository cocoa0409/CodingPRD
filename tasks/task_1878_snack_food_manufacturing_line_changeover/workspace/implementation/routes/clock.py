from flask import Blueprint

from auth import require
from errors import ApiError
from store import STORE
from util import body, iso, ok, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/snack-mfg/_clock/set_current_utc")
def set_clock():
    require(["PlantManager"])
    data = body()
    raw = data.get("to_iso8601")
    try:
        dt = parse_dt(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be a valid ISO 8601 timestamp")
    STORE.clock = dt
    return ok(STORE, {"current_utc": iso(STORE.clock)}, status=200)
