"""Test-driving logical clock endpoint (PRD §2.4)."""
from flask import Blueprint

from clock import clock_iso, parse_iso, clock
from errors import ApiError, ERR_VALIDATION
from helpers import get_body
from middleware import require_roles
from response import success_object
from services import expire_rights_for_passed_contracts

bp = Blueprint("clock_routes", __name__)


@bp.post("/rack/_clock/set_current_utc")
def set_current_utc():
    require_roles(["PlatformAdmin"])
    raw = get_body().get("to_iso8601")
    dt = parse_iso(raw)
    if dt is None:
        raise ApiError(
            ERR_VALIDATION, 400,
            "to_iso8601 must be an ISO 8601 UTC timestamp",
        )
    clock.set(dt)
    # Advancing the clock is not inert: rights tied to contracts whose
    # end_date has passed expire automatically.
    expire_rights_for_passed_contracts()
    return success_object({"current_utc": clock_iso()})
