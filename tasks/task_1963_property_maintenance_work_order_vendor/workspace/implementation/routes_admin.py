"""Test-driving logical clock endpoint (PRD 2.4)."""

from flask import Blueprint

from db import store
from errors import validation
from helpers import body
from middleware import authn, authorize
from response import ok_object
from timeutil import fmt_dt, parse_dt

bp = Blueprint("admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authn_role = authn()[1]
    authorize(authn_role, {"PropertyManager"})
    raw = body().get("to_iso8601")
    target = parse_dt(raw) if raw is not None else None
    if target is None:
        validation("to_iso8601 must be a well-formed ISO 8601 datetime")
    store.clock = target
    return ok_object({"current_utc": fmt_dt(store.clock)})
