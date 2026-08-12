"""Logical mill clock (PRD 2.5)."""
from flask import Blueprint

from db import set_clock, fmt_dt
from envelope import success
from middleware import authenticate, authorize
from services import expiry_sweep
from validation import get_body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
def set_current_utc():
    uid, role = authenticate()
    data = get_body()
    to = req_dt(data, "to_iso8601")
    authorize(role, uid, {"MillManager"})
    set_clock(to)
    expiry_sweep()
    return success({"current_utc": fmt_dt(to)}, 200)
