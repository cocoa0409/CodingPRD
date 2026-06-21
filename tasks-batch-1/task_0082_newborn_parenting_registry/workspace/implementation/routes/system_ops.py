"""Test-driving clock endpoint (PRD §2.9)."""

from flask import Blueprint

import db
from errors import invalid_request
from helpers import get_body, require_field
from middleware import require_roles
from response import ok_object

bp = Blueprint("system_ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("RegistrySupervisor")
    body = get_body()
    to_iso = require_field(body, "to_iso8601", str)
    try:
        dt = db.parse_iso(to_iso)
    except ValueError as e:
        raise invalid_request(str(e))
    canonical = db.fmt_iso(dt)
    db.set_clock(canonical)
    return ok_object({"current_utc": canonical})
