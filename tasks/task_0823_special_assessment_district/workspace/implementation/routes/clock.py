from flask import Blueprint

from store import set_clock
from web import protected, ok, body_json, require, as_str
from util import parse_dt
from logic import promote_all

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@protected(["DistrictAdministrator", "CountyTreasurer"])
def set_current_utc():
    b = body_json()
    iso = as_str(require(b, "to_iso8601"), "to_iso8601")
    try:
        dt = parse_dt(iso)
    except Exception:
        from web import ApiError
        raise ApiError("ERR_VALIDATION", "to_iso8601 must be a valid ISO-8601 instant")
    set_clock(dt)
    promote_all()
    return ok({})
