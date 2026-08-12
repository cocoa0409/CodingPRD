"""Test-driving logical clock (PRD 2.4)."""
from flask import Blueprint

from clock import set_logical_now
from helpers import actor, as_dt, body, req_field, require_roles
from response import ok
from util import fmt_iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _uid, role = actor()
    require_roles(role, ("TurnaroundManager",))
    b = body()
    to = as_dt(req_field(b, "to_iso8601"), "to_iso8601")
    set_logical_now(to)
    return ok({"current_utc": fmt_iso(to)})
