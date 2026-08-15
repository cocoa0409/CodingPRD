from flask import Blueprint

from core import body, db, iso, ok, parse_dt, req_str, require_roles
from core import ERR_INVALID_REQUEST  # noqa: F401  (kept for parity)
from core import ApiError

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PanelManager")
def set_current_utc():
    data = body()
    to_iso8601 = data.get("to_iso8601")
    if to_iso8601 is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: to_iso8601")
    db.clock = parse_dt(to_iso8601, "to_iso8601")
    return ok({"current_utc": iso(db.clock)})
