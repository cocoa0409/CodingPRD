"""The logical housing clock (PRD §2.5)."""

from flask import Blueprint

import validators as V
from auth import authenticate
from envelope import ok
from errors import fail
from store import STORE, iso_ms, parse_iso_datetime

bp = Blueprint("clock", __name__, url_prefix="/housing")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate(["BureauCoordinator"])
    body = V.json_body()
    to_iso8601 = V.field_str(body, "to_iso8601")
    parsed = parse_iso_datetime(to_iso8601)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 instant")

    previous = STORE.clock
    STORE.clock = parsed
    # Repositioning changes no entity state and runs no sweeps.
    return ok({"current_utc": iso_ms(parsed), "previous_utc": iso_ms(previous)})
