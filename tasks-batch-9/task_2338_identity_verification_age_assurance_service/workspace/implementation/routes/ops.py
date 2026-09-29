"""Operations sweep and the logical-clock control (PRD 2.4, 3.10)."""
from flask import Blueprint

import auth
import clock
import response
import schema
import services
from errors import fail
from schema import Field

bp = Blueprint("ops", __name__)

CLOCK_FIELDS = (
    Field("current_utc", "string", required=True),
)


@bp.post("/idv/retention-sweeps")
def retention_sweep():
    caller = auth.authenticate((auth.PLATFORM_ADMIN,))
    schema.no_body()
    return response.object_response(services.run_sweep(caller))


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authenticate((auth.PLATFORM_ADMIN,))
    values = schema.validate(schema.read_body(), CLOCK_FIELDS)
    parsed = clock.parse_iso(values["current_utc"])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 UTC timestamp.")
    clock.set_now(parsed)
    return response.object_response({"current_utc": clock.to_iso(parsed)})
