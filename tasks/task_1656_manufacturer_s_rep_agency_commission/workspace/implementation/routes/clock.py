from flask import Blueprint

import db
from db import iso, now, set_now
from errors import err
from middleware import api, body
from response import success_object
from services import run_sweep

bp = Blueprint("clock", __name__)


@bp.route("/rep-agency/_clock/set_current_utc", methods=["POST"])
@api(["AgencyAdmin"])
def set_current_utc():
    data = body()
    target = db.parse_ts(data.get("to_iso8601"))
    if target is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO-8601 timestamp")
    if target <= now():
        raise err("ERR_CLOCK_REGRESSION",
                  "to_iso8601 must be strictly later than the current clock")
    set_now(target)
    counts = run_sweep()
    return success_object({"current_utc": iso(now()), "swept_counts": counts})
