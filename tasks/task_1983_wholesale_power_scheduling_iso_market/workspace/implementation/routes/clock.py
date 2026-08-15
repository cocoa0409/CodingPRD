from flask import Blueprint

from auth import parse_auth, require_role
from db import store
from envelope import ok
from util import get_body, check_unknown, req_datetime
from services.availability import recompute_all_availability

bp = Blueprint("clock", __name__)


@bp.post("/market/_clock/set_current_utc")
def set_clock():
    auth = parse_auth()
    require_role(auth, ["IsoOperator"])
    body = get_body()
    check_unknown(body, {"to_iso8601"})
    _raw, dt = req_datetime(body, "to_iso8601")
    store.clock_now = dt
    store.clock_str = _raw.strip()
    # Advancing the clock re-evaluates availability for generators with
    # APPROVED outages (window entry/exit) with downstream cascades, and
    # sweeps open margin calls for time-based defaulting.
    recompute_all_availability()
    return ok({"current_utc": store.clock_str}, status=200)
