"""Logical clock endpoint (SystemAdmin-only)."""

from flask import Blueprint

import db
from errors import err, ERR_CLOCK_REGRESSION
from middleware import require_roles
from response import success
from util import get_body, require_fields, parse_iso, iso_format
from services.core import run_sweep

bp = Blueprint("clock", __name__)


@bp.route("/npdes/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles(["SystemAdmin"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    target = parse_iso(body["to_iso8601"], "to_iso8601")
    if target <= db.clock.now():
        raise err(ERR_CLOCK_REGRESSION, 400, "to_iso8601 must be strictly after the current logical clock")
    db.clock.set(target)
    transitions = run_sweep()
    return success(
        {
            "current_utc": iso_format(db.clock.now()),
            "transitions_applied": transitions,
        },
        200,
    )
