"""POST /_clock/set_current_utc — logical clock administration (PRD §2.4)."""

from flask import Blueprint

from clock import set_clock, now_iso_ms, parse_iso
from middleware import require_role
from util import get_json_body, check_unknown_fields, require_fields, err
from response import success_object
from errors import ERR_INVALID_REQUEST

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_role("TerritoryManager")
    body = get_json_body()
    check_unknown_fields(body, {"to_iso8601"})
    require_fields(body, ["to_iso8601"])
    to_iso = body["to_iso8601"]
    if not isinstance(to_iso, str):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a string")
    try:
        parse_iso(to_iso)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp")
    set_clock(to_iso)
    return success_object({"current_utc": now_iso_ms()})
