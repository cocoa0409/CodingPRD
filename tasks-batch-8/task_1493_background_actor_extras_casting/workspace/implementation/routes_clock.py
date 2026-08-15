"""Logical clock utility (lives outside the /central-casting prefix)."""
from flask import Blueprint

from db import STORE, fmt_dt, parse_dt
from errors import ApiError, ERR_VALIDATION
from middleware import auth, body, req_str
from response import ok_obj
from services import sweep_clock

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(["AgencyAdmin"])
    data = body()
    target_raw = req_str(data, "to_iso8601")
    target = parse_dt(target_raw)
    if target is None:
        raise ApiError(ERR_VALIDATION, 400, "to_iso8601 must be an ISO 8601 datetime")
    STORE.clock = target
    sweep_clock()
    return ok_obj({"current_utc": fmt_dt(STORE.clock)})
