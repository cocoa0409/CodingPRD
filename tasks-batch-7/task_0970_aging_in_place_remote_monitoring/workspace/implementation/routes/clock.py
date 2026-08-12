"""Test-driving logical clock."""
from flask import Blueprint

import db
import errors
from middleware import require_roles, get_body, req_dt
from response import ok
from services import run_sweeps
from util import iso

bp = Blueprint("clock", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    require_roles(["PlatformAdmin"])
    b = get_body()
    target = req_dt(b, "to_iso8601")
    if target < db.clock:
        raise errors.invalid_request("The logical clock cannot move backward")
    db.clock = target
    run_sweeps()
    return ok({"current_utc": iso(db.clock)})
