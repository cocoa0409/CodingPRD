"""Test-driving logical clock endpoint (PRD §2.5)."""

from flask import Blueprint

from db import CLOCK
from middleware import require_roles
from response import success_object
from util import body, parse_iso8601, req_str

bp = Blueprint("clock", __name__)


@bp.post("/recovery/_clock/set_current_utc")
@require_roles("SystemAdmin")
def set_current_utc():
    b = body()
    to_iso8601 = req_str(b, "to_iso8601")
    CLOCK.set(parse_iso8601(to_iso8601))
    return success_object({"current_utc": to_iso8601})
