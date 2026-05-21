"""Admin clock route — PRD §2.10."""

from __future__ import annotations

from flask import Blueprint

from app import clock
from app.envelope import success_response
from app.errors import bad_request
from app.routes._helpers import get_json_body, with_auth
from app.util import parse_iso_datetime, iso_utc


bp = Blueprint("clock_admin", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@with_auth("PlatformAdmin")
def advance_clock(caller):
    body = get_json_body()
    to = body.get("to")
    if not isinstance(to, str) or not to:
        raise bad_request("'to' is required and must be an ISO 8601 datetime string")
    target = parse_iso_datetime(to, "to")
    result = clock.advance_to(target)
    return success_response({"now": iso_utc(result)})
