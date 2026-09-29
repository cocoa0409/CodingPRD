"""The logical program clock (PRD 2.5).  No authentication headers required."""

from flask import Blueprint

from errors import fail
from guards import Fields, raw_body
from respond import ok
from store import parse_iso8601, set_clock

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    fields = Fields(raw_body())
    fields.text("to_iso8601")
    moment = parse_iso8601(fields["to_iso8601"])
    if moment is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO-8601 instant.")
    return ok({"current_utc": set_clock(moment)})
