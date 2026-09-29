"""The logical-clock test facility (PRD 2.4)."""

from flask import Blueprint

import response
from db import now, parse_instant, store
from errors import ApiError
from middleware import body_json, guard_optional
from services import domain

bp = Blueprint("clock", __name__)

OPERATOR_ROLES = ("PerformanceDirector", "Coach", "MedicalProvider", "FrontDesk")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    guard_optional(*OPERATOR_ROLES)
    body = body_json()
    raw = body.get("current_utc")
    parsed = parse_instant(raw)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "current_utc must be an RFC 3339 UTC instant")
    if parsed < now():
        raise ApiError(
            "ERR_CLOCK_REWIND_FORBIDDEN",
            "The logical clock is monotonic and may not be moved backwards",
        )
    store.clock = parsed
    documents_expired, packages_expired = domain.sweep_clock(parsed)
    return response.ok(
        {
            "current_utc": raw,
            "clearance_documents_expired_count": documents_expired,
            "packages_expired_count": packages_expired,
        }
    )
