"""Test-driving logical-clock endpoint (PRD §2.4)."""

from flask import Blueprint

from db import store
from middleware import require_roles, json_body, req_field, as_datetime
from response import ok_object
from util import parse_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"], strict_slashes=False)
def set_current_utc():
    require_roles("SystemAdmin")
    data = json_body()
    to_iso = as_datetime(req_field(data, "to_iso8601"), "to_iso8601")
    store.clock.set(parse_dt(to_iso, "to_iso8601"))
    return ok_object({}, 200)
