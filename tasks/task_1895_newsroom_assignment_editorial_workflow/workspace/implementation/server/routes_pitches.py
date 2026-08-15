"""Pitch intake and desk review per PRD 3.2."""

from flask import request

from .auth import require, require_owner
from .blueprint import bp
from .calc import desk_base_score
from .envelope import ok_list, ok_obj
from .errors import ApiError, invalid_state, not_found
from .serialize import ser_pitch, ser_story
from .store import STORE, new_entity, touch
from .util import (
    body,
    opt_enum,
    paged,
    pagination_params,
    req_dt,
    req_enum,
    req_str,
    sort_created,
)

DESKS = ("METRO", "BUSINESS", "SPORTS", "FEATURES")
URGENCIES = ("STANDARD", "URGENT", "BREAKING")
STORY_TYPES = ("PRINT", "DIGITAL", "BROADCAST")

PITCH_CREATE_ROLES = [
    "Reporter",
    "Photographer",
    "CopyEditor",
    "FactChecker",
    "LegalReviewer",
    "AssignmentEditor",
    "ManagingEditor",
]
PITCH_READ_ROLES = PITCH_CREATE_ROLES + ["NewsDirector"]
WITHDRAW_ROLES = PITCH_CREATE_ROLES


def get_pitch(pid):
    p = STORE.pitches.get(pid)
    if p is None:
        not_found("ERR_PITCH_NOT_FOUND", "Pitch")
    return p


@bp.post("/newsroom/pitches")
def create_pitch():
    uid, _role = require(PITCH_CREATE_ROLES)
    b = body()
    title = req_str(b, "title")
    summary = req_str(b, "summary")
    desk = req_enum(b, "desk", DESKS)
    deadline_at = req_dt(b, "deadline_at")
    urgency = opt_enum(b, "urgency", URGENCIES, "STANDARD")

    e = new_entity()
    e.update({
        "title": title,
        "summary": summary,
        "desk": desk,
        "urgency": urgency,
        "deadline_at": deadline_at,
        "submitting_staff_id": uid,
        "status": "SUBMITTED",
        "rework_round": 0,
        "greenlit_story_id": None,
    })
    STORE.pitches[e["id"]] = e
    return ok_obj(ser_pitch(e), 201)


@bp.get("/newsroom/pitches")
def list_pitches():
    require(PITCH_READ_ROLES)
    items = list(STORE.pitches.values())
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    desk = request.args.get("desk")
    if desk:
        items = [p for p in items if p["desk"] == desk]
    sub = request.args.get("submitting_staff_id")
    if sub:
        items = [p for p in items if p["submitting_staff_id"] == sub]
    gs = request.args.get("greenlit_story_id")
    if gs:
        items = [p for p in items if p["greenlit_story_id"] == gs]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_pitch(p) for p in page], limit, offset, total)


@bp.get("/newsroom/pitches/<pid>")
def read_pitch(pid):
    require(PITCH_READ_ROLES)
    return ok_obj(ser_pitch(get_pitch(pid)))


@bp.get("/newsroom/pitches/<pid>/stories")
def pitch_stories(pid):
    require(["AssignmentEditor", "ManagingEditor", "NewsDirector"])
    get_pitch(pid)
    items = [s for s in STORE.stories.values() if s["pitch_id"] == pid]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_story(s) for s in page], limit, offset, total)


@bp.post("/newsroom/pitches/<pid>/start-review")
def start_review(pid):
    require(["AssignmentEditor"])
    p = get_pitch(pid)
    if p["status"] != "SUBMITTED":
        invalid_state("Pitch is not SUBMITTED")
    p["status"] = "DESK_REVIEW"
    touch(p)
    return ok_obj(ser_pitch(p))


@bp.post("/newsroom/pitches/<pid>/return")
def return_pitch(pid):
    require(["AssignmentEditor"])
    p = get_pitch(pid)
    if p["status"] != "DESK_REVIEW":
        invalid_state("Pitch is not in DESK_REVIEW")
    if p["rework_round"] >= 3:
        raise ApiError(
            "ERR_PITCH_REWORK_LIMIT", 422, "Pitch has reached the rework limit"
        )
    p["status"] = "SUBMITTED"
    p["rework_round"] += 1
    touch(p)
    return ok_obj(ser_pitch(p))


@bp.post("/newsroom/pitches/<pid>/greenlight")
def greenlight_pitch(pid):
    require(["AssignmentEditor"])
    p = get_pitch(pid)
    b = body()
    story_type = req_enum(b, "story_type", STORY_TYPES)
    if p["status"] != "DESK_REVIEW":
        invalid_state("Pitch is not in DESK_REVIEW")

    story = new_entity()
    story.update({
        "pitch_id": p["id"],
        "desk": p["desk"],
        "story_type": story_type,
        "author_staff_id": p["submitting_staff_id"],
        "status": "DRAFT",
        "word_count": 0,
        "embargo_until": None,
        "slot_id": None,
        "priority_score": desk_base_score(p),
        "correction_count": 0,
        "published_at": None,
        "superseded_by_story_id": None,
    })
    STORE.stories[story["id"]] = story

    p["status"] = "GREENLIT"
    p["greenlit_story_id"] = story["id"]
    touch(p)
    return ok_obj(ser_pitch(p))


@bp.post("/newsroom/pitches/<pid>/reject")
def reject_pitch(pid):
    require(["AssignmentEditor"])
    p = get_pitch(pid)
    if p["status"] != "DESK_REVIEW":
        invalid_state("Pitch is not in DESK_REVIEW")
    p["status"] = "REJECTED"
    touch(p)
    return ok_obj(ser_pitch(p))


@bp.post("/newsroom/pitches/<pid>/withdraw")
def withdraw_pitch(pid):
    uid, _role = require(WITHDRAW_ROLES)
    p = get_pitch(pid)
    # Ownership (priority 6) is evaluated before state (priority 8).
    require_owner(uid, p["submitting_staff_id"])
    if p["status"] not in ("SUBMITTED", "DESK_REVIEW"):
        invalid_state("Pitch can no longer be withdrawn")
    p["status"] = "WITHDRAWN"
    touch(p)
    return ok_obj(ser_pitch(p))
