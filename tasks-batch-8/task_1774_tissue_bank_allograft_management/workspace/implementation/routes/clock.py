"""Logical clock driving capability (PRD §2.4)."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services import domain
from util import CLOCK, fmt_dt, parse_dt
from validate import get_body

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    caller = require_roles({"SupplyChainAdmin"})
    body = get_body()
    raw = body.get("to_iso8601")
    if raw is None:
        raise_error(ERR_INVALID_REQUEST, "missing required field: to_iso8601")
    try:
        target = parse_dt(raw)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime string")
    if target < CLOCK.now():
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 moves the logical clock backward")
    CLOCK.set(target)
    counts = domain.run_clock_sweeps(caller.user_id)
    return success_object({
        "current_utc": fmt_dt(CLOCK.now()),
        "documents_expired": counts["documents_expired"],
        "units_expired": counts["units_expired"],
        "reservations_expired": counts["reservations_expired"],
        "suppliers_auto_suspended": counts["suppliers_auto_suspended"],
    })
