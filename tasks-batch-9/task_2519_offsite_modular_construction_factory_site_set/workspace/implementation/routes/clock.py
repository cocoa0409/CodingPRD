"""The test-driving logical clock endpoint."""

from flask import Blueprint

import auth
import services
import validate
from envelope import ok
from errors import ApiError
from store import db

bp = Blueprint("clock", __name__)


@bp.post("/modular/_clock/set_current_utc")
@auth.endpoint("ProgramAdmin")
def set_current_utc():
    data = validate.body(optional=False)
    instant = validate.field_dt(data, "current_utc")

    # rank 80 — the logical clock never moves backwards
    if instant < db.clock:
        raise ApiError(
            "ERR_CLOCK_NOT_MONOTONIC",
            "current_utc is earlier than the clock's present value",
        )

    db.clock = instant
    services.sweep_clock(instant)
    return ok({})
