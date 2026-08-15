"""Logical clock endpoint: set current UTC and run the time-driven sweep."""

from flask import Blueprint

from db import db
from middleware import authenticate
from response import ok_object
from services import run_sweep
from util import get_body, iso, parse_datetime_value, req_str

bp = Blueprint("clock", __name__)


@bp.post("/clearance/_clock/set_current_utc")
def set_current_utc():
    authenticate(["SystemAdmin"])
    b = get_body()
    to_iso8601 = req_str(b, "to_iso8601")
    db.now = parse_datetime_value(to_iso8601)
    counts = run_sweep()
    return ok_object({
        "current_utc": iso(db.now),
        "staled_snapshots": counts["staled_snapshots"],
        "expired_authorizations": counts["expired_authorizations"],
        "expired_estimates": counts["expired_estimates"],
        "defaulted_plans": counts["defaulted_plans"],
    })
