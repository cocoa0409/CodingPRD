from __future__ import annotations

"""Test-driving logical clock."""
from flask import Blueprint, request

import db
import errors as E
import response
from middleware import require_auth
from services import validation as V


bp = Blueprint("clock", __name__)


@bp.route("/rush/_clock/set_current_utc", methods=["POST"])
@require_auth(["PanhellenicAdmin"])
def set_clock():
    body = request.get_json(silent=True) or {}
    raw = V.require_string(body, "to_iso8601")
    try:
        dt = db.parse_iso8601(raw)
    except ValueError:
        raise E.APIError(E.ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601 UTC")
    db.set_clock(dt)
    return response.success_object({"current_utc": db.format_ts(dt)})
