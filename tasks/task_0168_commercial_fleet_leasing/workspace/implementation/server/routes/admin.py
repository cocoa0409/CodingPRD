"""Test-driving endpoint: POST /_clock/advance (§3.10)."""
from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..clock import iso_format, now, parse_iso, set_clock
from ..common import get_json_body, require_fields
from ..errors import ApiError
from ..response import respond


bp = Blueprint("admin", __name__)


@bp.post("/_clock/advance")
@require_auth("FleetManager", "TaxAdmin")
def clock_advance():
    body = get_json_body()
    require_fields(body, "to")
    try:
        target = parse_iso(body["to"])
    except ValueError as exc:
        raise ApiError("ERR_VALIDATION", str(exc))
    set_clock(target)
    return respond({"now": iso_format(now())}, 200)
