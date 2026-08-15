"""POST /_clock/set_current_utc — logical clock control + estoppel sweep."""
from flask import Blueprint

import db
import services
from errors import ApiError, ERR_INVALID_REQUEST
from helpers import body, parse_instant
from middleware import require_roles
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("ProviderAdmin")
    b = body()
    raw = b.get("to_iso8601")
    if raw is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_iso8601 is required")
    dt = parse_instant(raw)
    db.set_clock(dt)
    services.estoppel_sweep()
    return success({"current_utc": db.fmt_ts(db.now())})
