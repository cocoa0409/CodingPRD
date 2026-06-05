"""Test-driving clock control (PRD §2.7)."""

from flask import Blueprint

from db import db
from errors import raise_api
from middleware import require_roles
from response import success
from services.body import get_json_body, require_string

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("Examiner")
def set_current_utc(_user_id, _role):
    body = get_json_body()
    to_iso8601 = require_string(body, "to_iso8601")
    try:
        db.set_clock(to_iso8601)
    except ValueError:
        raise_api("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 datetime")
    return success({"current_utc": db.current_utc_iso()}, 200)
