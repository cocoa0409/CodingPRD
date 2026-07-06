"""POST /_clock/set_current_utc — PlatformAdmin sets the logical clock."""
from flask import Blueprint, request

from middleware import auth_required
import db
from response import ok
from services import validators as v

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@auth_required("PlatformAdmin")
def set_clock():
    body = request.get_json(silent=True) or {}
    v.require_dict(body)
    dt, _ = v.require_datetime(body, "to_iso8601")
    db.set_clock(dt)
    return ok({})
