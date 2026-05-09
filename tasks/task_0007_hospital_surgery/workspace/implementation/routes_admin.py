from flask import Blueprint

from audit import write_audit
from calc import STERILIZATION_EXPIRY_MINUTES
from db import db
from errors import raise_error, ERR_INVALID_TIME_PARAMETERS
from middleware import auth_required
from response import success
from utils import get_json_body, require_int

bp = Blueprint("admin", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@auth_required("Scheduler")
def advance_clock():
    body = get_json_body()
    if "delta_minutes" not in body or body["delta_minutes"] is None:
        raise_error(ERR_INVALID_TIME_PARAMETERS, "delta_minutes is required and must be > 0")
    val = body["delta_minutes"]
    if isinstance(val, bool) or not isinstance(val, int):
        raise_error(ERR_INVALID_TIME_PARAMETERS, "delta_minutes must be an integer > 0")
    if val <= 0:
        raise_error(ERR_INVALID_TIME_PARAMETERS, "delta_minutes must be > 0")
    with db.lock:
        db.current_minute += val
        return success({"current_minute": db.current_minute})


@bp.route("/_sweep/sterilization", methods=["POST"])
@auth_required("Scheduler")
def sweep_sterilization():
    expired = 0
    with db.lock:
        for s in db.instrument_sets.values():
            if s["sterilization_status"] != "CLEAN_STERILIZED":
                continue
            last = s.get("last_sterilized_at_minute")
            if last is None:
                continue
            if (db.current_minute - last) >= STERILIZATION_EXPIRY_MINUTES:
                s["sterilization_status"] = "EXPIRED"
                db.stamp_update(s)
                write_audit("InstrumentSet", s["id"], "STERILIZATION_EXPIRED",
                            {"elapsed_minutes": db.current_minute - last})
                expired += 1
    return success({"expired_count": expired})
