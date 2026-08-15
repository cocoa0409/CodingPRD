"""Test-driving logical clock endpoint (PRD §2.6)."""

from flask import Blueprint

from clock import set_clock
from errors import ERR_VALIDATION, err
from middleware import require_auth, get_json_body, require_string
from response import success_object

bp = Blueprint("clock_admin", __name__)


@bp.post("/merch/_clock/set_current_utc")
def set_current_utc():
    require_auth()  # all four roles permitted
    body = get_json_body()
    to_iso8601 = require_string(body, "to_iso8601", required=True)
    try:
        set_clock(to_iso8601)
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, 400, "to_iso8601 must be an ISO 8601 datetime")
    return success_object({})
