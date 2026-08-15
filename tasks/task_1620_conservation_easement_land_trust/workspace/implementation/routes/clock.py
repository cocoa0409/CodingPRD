"""Test-driving logical clock (outside the /stewardship mount)."""
from flask import Blueprint

import db
import utils
from errors import ApiError
from middleware import body, require_roles
from response import ok
from services import domain

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("TrustAdmin")
def set_clock():
    b = body()
    target = utils.parse_instant(b.get("to_iso8601"))
    if target is None:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant.", 400)
    old_clock = db.get_clock()
    db.set_clock(target)
    domain.run_sweep(old_clock, target)
    return ok({"current_utc": utils.iso_instant(target)})
