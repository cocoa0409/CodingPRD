"""Logical clock endpoint (PRD §2.9). DrawOfficer only."""
from flask import Blueprint

from db import store, parse_dt
from errors import err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success
from validation import get_json_body, as_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("DrawOfficer")
def set_clock():
    body = get_json_body()
    to_iso = as_str(body, "to_iso8601", required=True)
    try:
        parse_dt(to_iso)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 datetime")
    store.set_clock(to_iso)
    return success({"current_utc": to_iso}, status=200, response_type="object")
