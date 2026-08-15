"""Logical clock endpoint (PRD §2.4)."""

from flask import Blueprint

import db
from errors import err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("ProgramManager")
    from routes.common import body, require_fields
    data = body()
    require_fields(data, ["to_iso8601"])
    to_iso = data["to_iso8601"]
    if not isinstance(to_iso, str):
        raise err(ERR_INVALID_REQUEST, 400, "to_iso8601 must be an ISO 8601 string")
    # Validate parseability
    try:
        db._parse_iso8601(to_iso)
    except Exception:
        raise err(ERR_INVALID_REQUEST, 400, "to_iso8601 is not a valid ISO 8601 UTC instant")
    db.set_logical_clock(to_iso)
    return success_object({"current_utc": to_iso}, 200)
