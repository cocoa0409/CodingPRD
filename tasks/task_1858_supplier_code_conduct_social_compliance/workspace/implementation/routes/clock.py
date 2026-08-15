"""Logical clock endpoint."""
from flask import Blueprint, request
import db
from middleware import require_roles
from response import success_object
from errors import raise_err, ERR_INVALID_REQUEST
from services.utils import parse_iso, to_iso_ms

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("SourcingProgramAdmin")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not to_iso:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 is required")
    dt = parse_iso(to_iso)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO-8601 datetime")
    db.set_clock(to_iso_ms(dt))
    return success_object({"current_utc": db.get_clock()})
