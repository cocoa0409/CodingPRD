"""Logical-clock endpoint (PRD 2.5): advances time and runs the expiry sweep."""
from datetime import datetime, timezone

from flask import Blueprint

from db import CLOCK
from errors import ApiError
from middleware import auth
from response import ok
from services import run_expiry_sweep
from util import body, parse_dt, required

bp = Blueprint("clock", __name__, url_prefix="/licensing/_clock")


@bp.post("/set_current_utc")
def set_current_utc():
    auth(["ComplianceAdmin"])
    data = body()
    raw = required(data, "to_iso8601")
    if not isinstance(raw, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be a string")
    try:
        parse_dt(raw)
    except Exception:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO 8601 UTC instant"
        )
    # The response echoes the administrator's supplied instant verbatim.
    CLOCK["current_utc"] = raw.strip()
    # Advancing the clock runs the license expiry sweep (PRD 3.5).
    run_expiry_sweep()
    return ok({"current_utc": CLOCK["current_utc"]})
