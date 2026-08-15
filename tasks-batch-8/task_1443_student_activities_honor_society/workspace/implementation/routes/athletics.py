"""AthleticsCalendarBlock endpoints."""

from flask import Blueprint

import db
from core import (as_str, body, check_frozen, get_block, get_chapter, new_record,
                  require_fields, touch)
from db import parse_dt
from errors import (ERR_INVALID_ATHLETICS_BLOCK, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND, ApiError)
from middleware import auth, require_roles
from response import (apply_filters, list_response, serialize, serialize_many,
                      sorted_items, success)

bp = Blueprint("athletics", __name__)

ALL = ("ActivitiesDirector", "Advisor", "Officer", "Member")
PRIORITIES = ("PRACTICE", "GAME", "TOURNAMENT")


@bp.route("/chapters/<chapterId>/athletics-blocks", methods=["POST"])
def create_block(chapterId):
    _, role = auth()
    require_roles(role, ("Advisor", "ActivitiesDirector"))
    ch = get_chapter(chapterId)
    check_frozen(ch)
    data = body()
    require_fields(data, ["member_id", "block_start", "block_end", "sport", "priority"])
    member_id = as_str(data["member_id"], "member_id")
    member = db.members.get(member_id)
    if member is None or member["chapter_id"] != ch["id"]:
        raise ApiError(ERR_NOT_FOUND, 404, f"Member not found: {member_id}")
    priority = as_str(data["priority"], "priority")
    if priority not in PRIORITIES:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "priority must be one of PRACTICE, GAME, TOURNAMENT")
    start = parse_dt(data["block_start"], "block_start")
    end = parse_dt(data["block_end"], "block_end")
    if not start < end:
        raise ApiError(ERR_INVALID_ATHLETICS_BLOCK, 422,
                       "block_start must be strictly before block_end")
    rec = new_record({
        "chapter_id": ch["id"],
        "member_id": member_id,
        "block_start": db.iso(start),
        "block_end": db.iso(end),
        "sport": as_str(data["sport"], "sport"),
        "priority": priority,
        "status": "ACTIVE",
    })
    db.athletics_blocks[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.route("/chapters/<chapterId>/athletics-blocks", methods=["GET"])
def list_blocks(chapterId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    items = [b for b in db.athletics_blocks.values() if b["chapter_id"] == ch["id"]]
    items = apply_filters(items, ["status", "member_id", "priority"])
    return list_response(serialize_many(sorted_items(items)))


@bp.route("/chapters/<chapterId>/athletics-blocks/<blockId>", methods=["GET"])
def fetch_block(chapterId, blockId):
    _, role = auth()
    require_roles(role, ALL)
    ch = get_chapter(chapterId)
    b = get_block(ch, blockId)
    return success(serialize(b), 200)


@bp.route("/chapters/<chapterId>/athletics-blocks/<blockId>/cancel", methods=["POST"])
def cancel_block(chapterId, blockId):
    _, role = auth()
    require_roles(role, ("Advisor", "ActivitiesDirector"))
    ch = get_chapter(chapterId)
    b = get_block(ch, blockId)
    check_frozen(ch)
    if b["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ACTIVE block can be cancelled")
    b["status"] = "CANCELLED"
    touch(b)
    return success(serialize(b), 200)
