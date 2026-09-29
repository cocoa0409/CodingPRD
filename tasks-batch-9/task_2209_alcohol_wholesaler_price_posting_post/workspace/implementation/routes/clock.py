"""The logical posting clock (PRD section 2.4)."""

from flask import Blueprint

from auth import ROLE_COMPLIANCE_OFFICER, authenticate
from envelope import object_response
from store import fmt_iso, parse_iso, set_clock
from validators import Field, validate_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate([ROLE_COMPLIANCE_OFFICER])
    values = validate_body([Field("to_iso8601", "datetime")])
    instant = parse_iso(values["to_iso8601"])
    set_clock(instant)
    return object_response({"current_utc": fmt_iso(instant)})
