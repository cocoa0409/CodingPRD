"""Deterministic test clock (PRD §3.9). Administrator-only."""
from flask import Blueprint, request

import db
from errors import fail, ERR_INVALID_REQUEST
from middleware import authorize
from response import success
from services.common import require_body, parse_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize({"Administrator"})
    data = require_body(request.get_json(silent=True))
    to_iso8601 = data.get("to_iso8601")
    if parse_dt(to_iso8601) is None:
        fail(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    db.set_clock(to_iso8601)
    # output: null -> empty object data, 200 OK (PRD §4).
    return success({}, status=200)
