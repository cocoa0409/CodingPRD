"""Test-driving logical clock endpoint (PRD §2.9)."""

from flask import Blueprint

from clock import CLOCK
from errors import invalid_request
from middleware import require_roles
from response import success_object
from validation import body

bp = Blueprint("clock_routes", __name__)


@bp.post("/fsa/_clock/set_current_utc")
def set_current_utc():
    require_roles(["CountySpecialist"])
    data = body()
    to_iso8601 = data.get("to_iso8601")
    if not isinstance(to_iso8601, str):
        raise invalid_request("to_iso8601 is required and must be an ISO 8601 string")
    try:
        current = CLOCK.set(to_iso8601)
    except (ValueError, TypeError):
        raise invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    from clock import iso_z
    return success_object({"current_utc": iso_z(current)})
