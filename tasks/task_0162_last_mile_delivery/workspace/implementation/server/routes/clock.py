"""Test-only clock advance endpoint."""
from flask import Blueprint

from ..auth import authed
from ..clock import clock, iso8601_ms, parse_iso8601
from ..envelope import success_object
from ..errors import raise_error
from ._helpers import get_json_body, require


bp = Blueprint("clock", __name__)


@bp.post("/_clock/advance")
@authed(["Dispatcher", "Driver", "Customer", "SortingHubOperator", "ComplianceOfficer"])
def advance(user_id, user_role):
    body = get_json_body()
    to_iso8601 = require(body, "to_iso8601")
    try:
        target = parse_iso8601(to_iso8601)
    except Exception:
        raise_error("ERR_REFERENCE_NOT_FOUND", "to_iso8601 invalid")
    current = clock.now()
    if target < current:
        raise_error("ERR_CLOCK_BACKWARDS")
    new_now = clock.advance_to(target)
    return success_object({"now": iso8601_ms(new_now)})
