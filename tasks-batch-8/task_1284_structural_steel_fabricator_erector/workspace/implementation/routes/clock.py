"""Logical clock test-driving endpoint (PRD 2.5)."""

from flask import Blueprint

from envelope import ok_object
from store import store
from validate import authenticate, get_body, req_datetime, require_role

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = authenticate()
    require_role(role, {"FABRICATOR_ADMIN"})
    body = get_body()
    instant = req_datetime(body, "to_iso8601")
    store.clock = instant
    return ok_object({}, 200)
