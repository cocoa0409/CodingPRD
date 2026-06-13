"""Test-driving clock endpoint (PRD §2.10). Exempt from auth."""
from flask import Blueprint

from db import db
from errors import err, ERR_INVALID_REQUEST
from response import success
from services.common import parse_body, require_str
from services.clock_util import _parse_iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    # exempt from authentication (PRD §2.1)
    body = parse_body()
    iso = require_str(body, "to_iso8601")
    try:
        dt = _parse_iso(iso)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    if dt is None:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    db.current_clock = dt
    # no resource payload
    return success({}, status=200)
