"""Test-driving endpoints: the logical clock and the rescission sweep."""

from flask import Blueprint

import auth
import derive
import errors
import validators
from envelope import ok
from errors import fail
from store import db

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.require(auth.PLATFORM_ADMIN)
    data = validators.body()
    target = validators.datetime_field(data, "to_iso8601")
    if target < db.now():
        fail(errors.ERR_CLOCK_NOT_MONOTONIC, "the logical clock may only move forward")
    previous = db.set_clock(target)
    return ok({"current_utc": db.now(), "previous_utc": previous})


@bp.post("/_ops/rescission-sweep")
def rescission_sweep():
    auth.require(auth.PLATFORM_ADMIN)
    now = db.now()
    candidates = [
        agreement
        for agreement in db.agreements.values()
        if agreement["rescission_status"] == "OPEN"
        and now > agreement["rescission_deadline_utc"]
    ]
    candidates.sort(key=lambda a: (a["executed_at"], a["created_at"], a["_seq"]))
    swept = []
    for agreement in candidates:
        derive.setf(agreement, "rescission_status", "EXPIRED")
        swept.append(agreement["id"])
    return ok(
        {
            "swept_count": len(swept),
            "expired_agreement_ids": swept,
            "clock_now": now,
        }
    )
