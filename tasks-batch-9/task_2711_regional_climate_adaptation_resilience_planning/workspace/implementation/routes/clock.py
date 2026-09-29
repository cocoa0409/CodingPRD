"""PRD 2.4 -- the logical clock.

The clock starts at 2026-08-01T00:00:00Z on server startup and only ever moves
when this endpoint is called; it never advances on its own.
"""

from flask import Blueprint

import envelope
import validate
from auth import ROLE_REGIONAL_ADMINISTRATOR, guard
from core import clock, iso

bp = Blueprint("clock", __name__)


@bp.post("/resilience/_clock/set_current_utc")
@guard(ROLE_REGIONAL_ADMINISTRATOR)
def set_current_utc():
    body = validate.json_body()
    moment = validate.datetime_field(body, "to_iso8601", required=True)
    clock.set(moment)
    return envelope.ok({"current_utc": iso(clock.now())})
