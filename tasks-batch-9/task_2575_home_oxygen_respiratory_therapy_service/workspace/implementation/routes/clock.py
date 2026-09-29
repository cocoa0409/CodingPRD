"""Logical clock endpoint.

The clock starts at exactly 2026-08-01T00:00:00Z and never reads real
wall-clock time. Every successful advance runs the certificate expiry sweep
(and its contract-suspension cascade) before returning.
"""
from flask import Blueprint

from core import (
    ROLE_MANAGER,
    ApiError,
    authenticate,
    db,
    iso,
    parse_datetime,
    respond,
)
from domain import clock_sweep
from validate import Field, validate

bp = Blueprint("clock", __name__)

CLOCK_FIELDS = [Field("to_iso8601", "datetime", required=True)]


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate((ROLE_MANAGER,))
    data = validate(CLOCK_FIELDS)
    target = parse_datetime(data["to_iso8601"])
    previous = db.clock
    if target <= previous:
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    db.clock = target
    expired, suspended = clock_sweep(target)
    return respond(
        {
            "current_utc": iso(db.clock),
            "previous_utc": iso(previous),
            "expired_cmn_count": expired,
            "suspended_contract_count": suspended,
        }
    )
