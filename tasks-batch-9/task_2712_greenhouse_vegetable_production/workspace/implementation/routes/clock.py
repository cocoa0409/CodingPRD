"""Test-driving endpoint for the server-held logical clock."""
from flask import Blueprint

import calc
import fields
from authz import GROWER_MANAGER, body, guard
from envelope import ok
from store import db, ordered, set_clock, touch

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@guard([GROWER_MANAGER])
def set_current_utc():
    payload = body()
    instant = fields.timestamp(payload, "current_utc")
    set_clock(instant)

    # Every ACTIVE window whose end has passed expires.
    for strategy in ordered("climate_strategies"):
        if strategy["status"] != "ACTIVE":
            continue
        if strategy["window_end"] <= instant:
            strategy["status"] = "EXPIRED"
            touch(strategy)
    # Re-derive every zone: an elapsed re-entry interval releases the IPM lock.
    for zone in ordered("zones"):
        calc.refresh_zone(zone)
    return ok({})
