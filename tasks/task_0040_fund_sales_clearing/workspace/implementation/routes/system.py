"""Clock control endpoints."""
from flask import Blueprint

from clock import now, set_now, parse_iso, iso
from errors import err
from middleware import require_auth
from response import success
from services.util import get_body, require_field


bp = Blueprint("system", __name__)


@bp.route("/_clock/advance", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def clock_advance():
    body = get_body()
    require_field(body, "now")
    try:
        target = parse_iso(body["now"])
    except ValueError:
        raise err("ERR_VALIDATION", "now must be ISO 8601")
    if target <= now():
        raise err("ERR_CLOCK_NOT_MONOTONIC", "Clock must advance monotonically")
    set_now(target)
    return success({"id": "clock", "now": iso(now())}, 200)


@bp.route("/_clock", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceReviewer", "NavOperator",
                      "ClearingOperator", "ProductOperator", "Investor"})
def get_clock():
    return success({"id": "clock", "now": iso(now())}, 200)
