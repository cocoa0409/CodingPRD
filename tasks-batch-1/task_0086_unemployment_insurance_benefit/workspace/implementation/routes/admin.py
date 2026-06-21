"""Test-hook: clock setter (PRD §3.10). /_ledger hook lives in claims.py."""
from flask import Blueprint

from clock import clock
from errors import err
from middleware import authenticate, require_role
from response import object_response
from validate import as_string, get_json_body

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    p = authenticate()
    require_role(p, {"ProgramAdmin"})
    body = get_json_body()
    to_iso = as_string(body, "to_iso8601")
    try:
        clock.set_iso(to_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant.")
    # 200 OK with empty data object (PRD §4)
    return object_response({}, 200)
