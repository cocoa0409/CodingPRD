"""Logical clock admin endpoint (PRD 2.8)."""
from flask import Blueprint

from db import clock_now_iso, clock_set
from middleware import auth
from response import ok
from services import run_clock_transitions
from util import body, parse_dt, required

bp = Blueprint("clock", __name__)


@bp.post("/accreditation/_clock/set_current_utc")
def set_clock():
    auth(["AccreditationOfficer"])
    data = body()
    to_iso = required(data, "to_iso8601")
    dt = parse_dt(to_iso, "to_iso8601")
    clock_set(dt)
    run_clock_transitions()
    return ok({"current_utc": clock_now_iso()})
