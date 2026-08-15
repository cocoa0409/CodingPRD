"""Test-driving logical clock: FacilityAdmin-only. The clock never falls
back to wall-clock time."""

from flask import Blueprint

import db
from db import iso
from middleware import auth_context, require_role
from response import ok
from validate import body, req_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = auth_context()
    require_role(role, ["FacilityAdmin"])
    data = body()
    dt = req_datetime(data, "to_iso8601")
    db.STORE.clock = dt
    return ok({"current_utc": iso(db.STORE.clock)})
