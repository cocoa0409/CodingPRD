"""Test-driving logical clock endpoint."""

from flask import Blueprint

from store import set_clock
from util import auth, require_role, ok_object, body_json, req_str, parse_iso

bp = Blueprint("clock", __name__)


@bp.post("/greenpower/_clock/set_current_utc")
def set_current_utc():
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    body = body_json()
    raw = req_str(body, "to_iso8601")
    dt = parse_iso(raw, "to_iso8601")
    set_clock(dt)
    return ok_object({"current_utc": raw})
