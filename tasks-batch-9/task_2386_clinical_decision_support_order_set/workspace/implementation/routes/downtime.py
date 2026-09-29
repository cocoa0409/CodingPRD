"""Downtime declaration, activation and closure (PRD §2.11, §3.9)."""
from flask import Blueprint

import const
import validate
from common import base_record, now, touch
from db import db
from errors import ApiError
from middleware import authenticate, caller_id, get_downtime
from response import created, ok

bp = Blueprint("downtime", __name__)


def _scopes_intersect(left, right):
    if left == "SYSTEM_WIDE" or right == "SYSTEM_WIDE":
        return True
    return left == right


@bp.post("/cds/downtime-events")
def create_downtime():
    authenticate((const.SYSTEM_ADMIN,))
    data = validate.body()

    scope = validate.enum(data, "scope", const.DOWNTIME_SCOPES, required=True)
    mode = validate.enum(data, "mode", const.DOWNTIME_MODES, required=True)
    window_start = validate.instant(data, "window_start", required=True)
    window_end = validate.instant(data, "window_end", required=True)
    planned = validate.boolean(data, "planned", default=True)
    reason = validate.string(data, "reason")

    if not window_start < window_end:
        raise ApiError("ERR_INVALID_WINDOW_BOUNDS", "window_end must be strictly after window_start")

    # Downtime intervals are closed: touching endpoints do conflict (PRD §3.9).
    for existing in sorted(db.downtime_events.values(), key=lambda e: e.get("_seq", 0)):
        if existing["state"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if not _scopes_intersect(scope, existing["scope"]):
            continue
        if window_start <= existing["window_end"] and existing["window_start"] <= window_end:
            raise ApiError(
                "ERR_DOWNTIME_WINDOW_OVERLAP",
                "The interval overlaps an existing downtime event with an intersecting scope",
            )

    event = base_record()
    event.update({
        "scope": scope,
        "mode": mode,
        "window_start": window_start,
        "window_end": window_end,
        "planned": planned,
        "reason": reason,
        "state": "SCHEDULED",
        "declared_by_user_id": caller_id(),
        "blocked_mutation_count": 0,
        "activated_at": None,
        "closed_at": None,
    })
    db.downtime_events[event["id"]] = event
    return created(event)


@bp.get("/cds/downtime-events/<cid>")
def read_downtime(cid):
    authenticate(const.ANY_ROLE)
    return ok(get_downtime(cid))


@bp.post("/cds/downtime-events/<cid>/activate")
def activate_downtime(cid):
    authenticate((const.SYSTEM_ADMIN,))
    event = get_downtime(cid)
    data = validate.body()
    validate.string(data, "activation_note")

    current = now()
    if (event["state"] != "SCHEDULED"
            or current < event["window_start"]
            or current > event["window_end"]):
        raise ApiError(
            "ERR_DOWNTIME_EVENT_NOT_SCHEDULED",
            "Only a SCHEDULED event inside its window may be activated",
        )

    event["state"] = "ACTIVE"
    event["activated_at"] = current
    touch(event)
    return ok(event)


@bp.post("/cds/downtime-events/<cid>/close")
def close_downtime(cid):
    authenticate((const.SYSTEM_ADMIN,))
    event = get_downtime(cid)
    data = validate.body()
    validate.string(data, "closure_note")

    if event["state"] not in ("SCHEDULED", "ACTIVE"):
        raise ApiError("ERR_DOWNTIME_EVENT_NOT_CLOSEABLE", "Downtime event is already terminal")

    event["state"] = "CLOSED" if event["state"] == "ACTIVE" else "CANCELLED"
    event["closed_at"] = now()
    touch(event)
    return ok(event)
