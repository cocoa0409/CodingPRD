"""Breaking news events, the bump cascade, and staffing call-ins per PRD 3.8."""

from datetime import timedelta

from flask import request

from .auth import require, require_owner
from .blueprint import bp
from .calc import (
    BUMP_FLOOR,
    CALL_IN_TTL_MINUTES,
    recompute_active_assignment_count,
    recompute_slot_reserved_count,
)
from .envelope import ok_list, ok_obj
from .errors import ApiError, invalid_state, not_found
from .serialize import ser_assignment, ser_call_in, ser_event
from .store import STORE, new_entity, now, touch
from .util import (
    body,
    opt_int,
    paged,
    pagination_params,
    req_dt,
    req_int,
    req_str,
    sort_created,
)

EVENT_READ_ROLES = ["NewsDirector", "AssignmentEditor", "ManagingEditor"]
FIELD_ROLES = ["Reporter", "Photographer"]
BUMPABLE_STORY_STATES = (
    "DRAFT",
    "IN_EDIT",
    "FACT_CHECK",
    "LEGAL_REVIEW",
    "CLEARED",
    "SCHEDULED",
)


def get_event(eid):
    e = STORE.events.get(eid)
    if e is None:
        not_found("ERR_EVENT_NOT_FOUND", "BreakingNewsEvent")
    return e


def get_call_in(cid):
    c = STORE.call_ins.get(cid)
    if c is None:
        not_found("ERR_CALL_IN_NOT_FOUND", "StaffCallIn")
    return c


@bp.post("/newsroom/breaking-events")
def declare_event():
    uid, _role = require(["NewsDirector"])
    b = body()
    title = req_str(b, "title")
    priority_band = req_int(b, "priority_band")
    if priority_band not in (1, 2, 3):
        from .errors import bad_request

        bad_request("priority_band must be 1, 2, or 3")
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    call_in_pool_size = opt_int(b, "call_in_pool_size", 2, minimum=0)

    if window_end <= window_start:
        raise ApiError(
            "ERR_INVALID_INTERVAL", 422, "window_end must be strictly after window_start"
        )

    e = new_entity()
    e.update({
        "title": title,
        "priority_band": priority_band,
        "window_start": window_start,
        "window_end": window_end,
        "call_in_pool_size": call_in_pool_size,
        "status": "DECLARED",
        "declared_by": uid,
        "resolved_at": None,
    })
    STORE.events[e["id"]] = e
    return ok_obj(ser_event(e), 201)


@bp.get("/newsroom/breaking-events")
def list_events():
    require(EVENT_READ_ROLES)
    items = list(STORE.events.values())
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_event(e) for e in page], limit, offset, total)


@bp.get("/newsroom/breaking-events/<eid>")
def read_event(eid):
    require(EVENT_READ_ROLES)
    return ok_obj(ser_event(get_event(eid)))


@bp.post("/newsroom/breaking-events/<eid>/activate")
def activate_event(eid):
    require(["NewsDirector"])
    e = get_event(eid)
    if e["status"] != "DECLARED":
        invalid_state("Event is not DECLARED")

    floor = BUMP_FLOOR[e["priority_band"]]

    # Hop 1: bump intersecting low-priority ACCEPTED assignments.
    bumped = []
    for a in list(STORE.assignments.values()):
        if a["status"] != "ACCEPTED":
            continue
        if not (a["start_at"] < e["window_end"] and a["end_at"] > e["window_start"]):
            continue
        story = STORE.stories.get(a["story_id"])
        if story is None:
            continue
        if story["priority_score"] < floor:
            a["status"] = "BUMPED"
            a["bumped_by_event_id"] = e["id"]
            touch(a)
            bumped.append(a)

    affected_staff = {a["staff_id"] for a in bumped}
    for sid in affected_staff:
        recompute_active_assignment_count(sid)

    # Hop 2: each bumped story with zero remaining REPORTER assignments in
    # {PROPOSED, ACCEPTED} moves to ON_HOLD. Hop 3: a held story that was
    # SCHEDULED releases its slot.
    bumped_story_ids = []
    seen = set()
    for a in bumped:
        if a["story_id"] not in seen:
            seen.add(a["story_id"])
            bumped_story_ids.append(a["story_id"])

    slots_to_recount = set()
    for story_id in bumped_story_ids:
        story = STORE.stories.get(story_id)
        if story is None:
            continue
        remaining_reporters = sum(
            1
            for x in STORE.assignments.values()
            if x["story_id"] == story_id
            and x["assignment_role"] == "REPORTER"
            and x["status"] in ("PROPOSED", "ACCEPTED")
        )
        if remaining_reporters > 0:
            continue
        if story["status"] not in BUMPABLE_STORY_STATES:
            continue
        was_scheduled = story["status"] == "SCHEDULED"
        old_slot = story["slot_id"] if was_scheduled else None
        if was_scheduled:
            story["slot_id"] = None
        story["status"] = "ON_HOLD"
        touch(story)
        if old_slot is not None:
            slots_to_recount.add(old_slot)
    for slot_id in slots_to_recount:
        recompute_slot_reserved_count(slot_id)

    # Selector (independent fan-out): page up to call_in_pool_size eligible staff.
    eligible = [
        s
        for s in STORE.staff.values()
        if s["employment_status"] == "ACTIVE"
        and s["role_capability"] in ("REPORTER", "PHOTOGRAPHER")
    ]
    eligible.sort(
        key=lambda s: (s["active_assignment_count"], s["created_at"], s["_seq"])
    )
    paged_at = now()
    for s in eligible[: e["call_in_pool_size"]]:
        ci = new_entity()
        ci.update({
            "event_id": e["id"],
            "staff_id": s["id"],
            "status": "PAGED",
            "paged_at": paged_at,
            "expires_at": paged_at + timedelta(minutes=CALL_IN_TTL_MINUTES),
        })
        STORE.call_ins[ci["id"]] = ci

    e["status"] = "ACTIVE"
    touch(e)
    return ok_obj(ser_event(e))


@bp.post("/newsroom/breaking-events/<eid>/resolve")
def resolve_event(eid):
    require(["NewsDirector"])
    e = get_event(eid)
    if e["status"] != "ACTIVE":
        invalid_state("Event is not ACTIVE")
    e["status"] = "RESOLVED"
    e["resolved_at"] = now()
    touch(e)
    for ci in STORE.call_ins.values():
        if ci["event_id"] == e["id"] and ci["status"] == "PAGED":
            ci["status"] = "EXPIRED"
            touch(ci)
    return ok_obj(ser_event(e))


@bp.get("/newsroom/breaking-events/<eid>/call-ins")
def event_call_ins(eid):
    require(["NewsDirector"])
    get_event(eid)
    items = [c for c in STORE.call_ins.values() if c["event_id"] == eid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_call_in(c) for c in page], limit, offset, total)


@bp.get("/newsroom/breaking-events/<eid>/assignments")
def event_assignments(eid):
    require(["NewsDirector"])
    get_event(eid)
    items = [
        a for a in STORE.assignments.values() if a.get("bumped_by_event_id") == eid
    ]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_assignment(a) for a in page], limit, offset, total)


def _answer_call_in(cid, target_status):
    uid, _role = require(FIELD_ROLES)
    c = get_call_in(cid)
    require_owner(uid, c["staff_id"])
    if c["status"] != "PAGED":
        invalid_state("Call-in is not PAGED")
    if now() >= c["expires_at"]:
        c["status"] = "EXPIRED"
        touch(c)
        raise ApiError(
            "ERR_CALL_IN_EXPIRED", 409, "Call-in has expired"
        )
    c["status"] = target_status
    touch(c)
    return ok_obj(ser_call_in(c))


@bp.post("/newsroom/call-ins/<cid>/confirm")
def confirm_call_in(cid):
    return _answer_call_in(cid, "CONFIRMED")


@bp.post("/newsroom/call-ins/<cid>/decline")
def decline_call_in(cid):
    return _answer_call_in(cid, "DECLINED")
