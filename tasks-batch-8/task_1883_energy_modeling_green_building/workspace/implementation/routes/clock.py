"""Logical clock endpoint (PRD 2.10)."""
from flask import Blueprint

from db import CLOCK
from middleware import auth_headers, require_role
from response import ok
from util import as_dt, body, required

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _user_id, role = auth_headers()
    data = body()
    to_iso8601 = as_dt(required(data, "to_iso8601"), "to_iso8601")
    require_role(role, {"ProgramAdmin"})
    CLOCK["current_utc"] = to_iso8601
    return ok({"current_utc": CLOCK["current_utc"]})
