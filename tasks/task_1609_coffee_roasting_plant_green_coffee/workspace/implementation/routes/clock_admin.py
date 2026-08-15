"""POST /roastery/_clock/set_current_utc — logical clock administration (PRD §2.11)."""

from flask import Blueprint

from clock import now_iso, parse_iso, set_clock
from errors import ERR_INVALID_REQUEST, err
from middleware import get_json_body, require_fields, require_role
from response import success_object

bp = Blueprint("clock_admin", __name__)


@bp.post("/roastery/_clock/set_current_utc")
def set_current_utc():
    require_role("PlatformAdmin")
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    to_iso = body["to_iso8601"]
    if not isinstance(to_iso, str):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a string")
    try:
        parse_iso(to_iso)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    set_clock(to_iso)
    return success_object({"current_utc": now_iso()})
