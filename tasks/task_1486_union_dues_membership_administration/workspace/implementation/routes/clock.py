"""Test-driving logical clock endpoint (outside the /api business surface)."""
from flask import Blueprint, request

import db
import errors
import utils
from middleware import require_roles
from response import ok

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("ParentBodyAdmin")
def set_current_utc(user_id, role):
    body = request.get_json(silent=True) or {}
    to_iso = utils.require_field(body, "to_iso8601")
    dt = utils.parse_datetime(to_iso)
    db.set_clock(dt)
    return ok({"current_utc": db.fmt_ts(db.now())}, 200)
