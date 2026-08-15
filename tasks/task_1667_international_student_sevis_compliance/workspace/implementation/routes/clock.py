"""Logical clock endpoint (PRD §2.5). Mounted at the server root."""

from flask import Blueprint

import db
import services
from errors import ERR_INVALID_REQUEST, raise_error
from helpers import body, req_field
from middleware import require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles(("PDSO", "DSO"))
    data = body()
    to_iso = req_field(data, "to_iso8601")
    if not isinstance(to_iso, str):
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime string")
    try:
        db.parse_clock(to_iso)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 datetime")
    db.current_utc_iso = to_iso
    sweeps_applied = services.run_sweeps()
    return success_object(
        {"current_utc": db.current_utc_iso, "sweeps_applied": sweeps_applied}, 200
    )
