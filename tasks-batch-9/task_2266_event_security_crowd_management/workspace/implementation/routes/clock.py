"""Logical clock control (PRD 2.4, 3.5)."""

from flask import Blueprint

import engine
import valid
from auth import authenticate
from db import clock_iso, db
from response import object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate({"SystemOperator"})
    payload = valid.body()
    to_iso8601 = valid.req_datetime(payload, "to_iso8601")

    db.clock = to_iso8601[1]
    expired_guard_count, voided_assignment_count = engine.credential_expiry_sweep()
    return object_response(
        {
            "current_utc": clock_iso(),
            "expired_guard_count": expired_guard_count,
            "voided_assignment_count": voided_assignment_count,
        }
    )
