"""Logical clock test-driving endpoint (PRD 2.5)."""

from flask import Blueprint

import db
from db import bump, parse_ts, format_clock
from errors import invalid
from middleware import caller, admit, body
from response import ok_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = caller()
    admit(role, ("FirmAdmin",))
    data = body()

    to_iso8601 = data.get("to_iso8601")
    try:
        target = db.parse_input_ts(to_iso8601)
    except (ValueError, TypeError):
        raise invalid("to_iso8601 must be an ISO 8601 timestamp")

    # Arbitrary target instants allowed; no monotonicity constraint.
    db.store.clock = target

    # Waiver-expiry sweep: every SENT waiver with expires_at <= new time
    # becomes EXPIRED (inclusive boundary).
    expired_ids = []
    for waiver in db.store.waiver_requests.values():
        if waiver["status"] != "SENT" or waiver["expires_at"] is None:
            continue
        if parse_ts(waiver["expires_at"]) <= target:
            waiver["status"] = "EXPIRED"
            bump(waiver)
            expired_ids.append(waiver["id"])

    return ok_object({
        "current_utc": format_clock(target),
        "expired_waiver_ids": expired_ids,
    })
