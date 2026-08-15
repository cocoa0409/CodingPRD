"""Logical clock control (PRD §2.9). IntegratorAdmin only."""
from flask import Blueprint

import db
import utils
from errors import ApiError
from middleware import body, require_roles
from response import ok

bp = Blueprint("clock", __name__)


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
@require_roles("IntegratorAdmin")
def set_clock():
    b = body()
    target = utils.parse_instant(b.get("to_iso8601"))
    if target is None:
        raise ApiError(
            "ERR_QUANTITY_INVALID",
            "to_iso8601 must be a valid ISO 8601 timestamp.",
            422,
        )
    db.set_clock(target)
    return ok({"current_utc": utils.iso_instant(target)})
