"""Administrative operations: the hold sweep and the logical clock (PRD 2.5, 3.3)."""

from flask import Blueprint

import clock
import validate
from errors import err
from middleware import body, endpoint
from response import object_response
from services import engine
from util import iso_instant, parse_instant

bp = Blueprint("ops", __name__)


@bp.post("/_ops/hold-sweep")
@endpoint("VenueAdmin")
def hold_sweep():
    return object_response(engine.run_hold_sweep())


@bp.post("/_clock/set_current_utc")
@endpoint("VenueAdmin")
def set_current_utc():
    payload = body()
    raw = validate.req_string(payload, "to_iso8601")
    instant = parse_instant(raw)
    if instant is None:
        raise err("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO 8601 instant.")
    clock.set_now(instant)
    return object_response({"current_utc": iso_instant(clock.now())})
