"""Publication slots per PRD 3.5."""

from datetime import timedelta

from flask import request

from .auth import require
from .blueprint import bp
from .envelope import ok_list, ok_obj
from .errors import ApiError, invalid_state, not_found
from .serialize import ser_slot, ser_story
from .store import STORE, new_entity, touch
from .util import (
    body,
    paged,
    pagination_params,
    req_dt,
    req_enum,
    req_int,
    sort_created,
)

CHANNELS = ("PRINT", "DIGITAL", "BROADCAST")
ALL_READ_ROLES = [
    "Reporter",
    "Photographer",
    "CopyEditor",
    "FactChecker",
    "LegalReviewer",
    "AssignmentEditor",
    "ManagingEditor",
    "NewsDirector",
    "AnalyticsProducer",
]
SLOT_GAP = timedelta(minutes=30)


def get_slot(sid):
    s = STORE.slots.get(sid)
    if s is None:
        not_found("ERR_SLOT_NOT_FOUND", "PublicationSlot")
    return s


@bp.post("/newsroom/slots")
def create_slot():
    require(["AssignmentEditor", "ManagingEditor"])
    b = body()
    channel = req_enum(b, "channel", CHANNELS)
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    capacity = req_int(b, "capacity", minimum=1)

    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_INTERVAL", 422, "window_end must be strictly after window_start"
        )
    # Same-channel ACTIVE slots must keep a strictly-more-than-30-minute gap;
    # an exact 30-minute gap (inclusive boundary) still conflicts.
    for other in STORE.slots.values():
        if other["channel"] != channel or other["status"] != "ACTIVE":
            continue
        separated = (
            window_start - other["window_end"] > SLOT_GAP
            or other["window_start"] - window_end > SLOT_GAP
        )
        if not separated:
            raise ApiError(
                "ERR_SLOT_WINDOW_CONFLICT",
                409,
                "Same-channel slots must keep a gap of more than 30 minutes",
            )

    e = new_entity()
    e.update({
        "channel": channel,
        "window_start": window_start,
        "window_end": window_end,
        "capacity": capacity,
        "reserved_count": 0,
        "status": "ACTIVE",
    })
    STORE.slots[e["id"]] = e
    return ok_obj(ser_slot(e), 201)


@bp.get("/newsroom/slots")
def list_slots():
    require(ALL_READ_ROLES)
    items = list(STORE.slots.values())
    channel = request.args.get("channel")
    if channel:
        items = [s for s in items if s["channel"] == channel]
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_slot(s) for s in page], limit, offset, total)


@bp.get("/newsroom/slots/<sid>")
def read_slot(sid):
    require(ALL_READ_ROLES)
    return ok_obj(ser_slot(get_slot(sid)))


@bp.get("/newsroom/slots/<sid>/stories")
def slot_stories(sid):
    require(["AssignmentEditor", "ManagingEditor", "NewsDirector"])
    get_slot(sid)
    items = [s for s in STORE.stories.values() if s.get("slot_id") == sid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_story(s) for s in page], limit, offset, total)


@bp.post("/newsroom/slots/<sid>/cancel")
def cancel_slot(sid):
    require(["ManagingEditor"])
    s = get_slot(sid)
    if s["status"] != "ACTIVE":
        invalid_state("Slot is not ACTIVE")
    if s["reserved_count"] != 0:
        raise ApiError(
            "ERR_SLOT_NOT_EMPTY", 409, "Slot has reservations outstanding"
        )
    s["status"] = "CANCELLED"
    touch(s)
    return ok_obj(ser_slot(s))
