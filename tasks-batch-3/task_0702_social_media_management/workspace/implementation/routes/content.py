"""Content item, content target, and scheduling routes (PRD §3.3)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import response
from errors import (
    err, ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_CLIENT_NOT_ACTIVE,
    ERR_CROSS_CLIENT_REFERENCE, ERR_CHANNEL_NOT_LIVE, ERR_SLOT_OVERLAP,
    ERR_POST_QUOTA_EXCEEDED,
)
from middleware import (
    get_user_context, require_role, get_json_body, get_pagination,
    require_string, optional_int,
)
from services import lookup, listing, slots as slot_geom
from services.serialize import content_item_out, content_target_out
from services.budget import count_posts_published_this_cycle

bp = Blueprint("content", __name__)


# ---------------- Content items ----------------

@bp.post("/content-items")
def create_content_item():
    _, role = get_user_context()
    require_role(role, {"ContentCreator", "AccountManager"})
    body = get_json_body()
    client_id = require_string(body, "client_id")
    with db.LOCK:
        lookup.get_client(client_id)
        author_id = require_string(body, "author_id")
        title = require_string(body, "title")
        post_body = require_string(body, "body")
        ci = {
            "id": db.new_id(),
            "client_id": client_id,
            "author_id": author_id,
            "title": title,
            "body": post_body,
            "status": "DRAFT",
            "revision_round": 0,
            "published_cycle_index": None,
            "scheduled_slot_id": None,
        }
        db.stamp_create(ci, full=True)
        db.content_items[ci["id"]] = ci
        return response.created(content_item_out(ci))


@bp.get("/content-items")
def list_content_items():
    _, role = get_user_context()
    require_role(role, {"ContentCreator", "AccountManager", "Approver", "PlatformAdmin"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.content_items.values()), {
            "client_id": request.args.get("client_id"),
            "status": request.args.get("status"),
            "scheduled_slot_id": request.args.get("scheduled_slot_id"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([content_item_out(c) for c in window], limit, offset, total)


@bp.get("/content-items/<content_item_id>")
def get_content_item(content_item_id):
    _, role = get_user_context()
    require_role(role, {"ContentCreator", "AccountManager", "Approver", "PlatformAdmin"})
    with db.LOCK:
        ci = lookup.get_content(content_item_id)
        return response.ok(content_item_out(ci))


@bp.post("/content-items/<content_item_id>/submit")
def submit_content_item(content_item_id):
    _, role = get_user_context()
    require_role(role, {"ContentCreator"})
    with db.LOCK:
        ci = lookup.get_content(content_item_id)
        if ci["status"] != "DRAFT":
            raise err(ERR_INVALID_STATE, "Content must be DRAFT to submit")
        # cross-entity state: owning client must be ACTIVE
        client = lookup.get_client(ci["client_id"])
        if client["status"] != "ACTIVE":
            raise err(ERR_CLIENT_NOT_ACTIVE, "Owning client must be ACTIVE to submit content")
        # must have at least one content target
        has_target = any(
            t["content_item_id"] == content_item_id for t in db.content_targets.values()
        )
        if not has_target:
            raise err(ERR_INVALID_STATE, "Content must have at least one target to submit")
        ci["status"] = "IN_REVIEW"
        db.touch(ci)
        return response.ok(content_item_out(ci))


@bp.post("/content-items/<content_item_id>/request-changes")
def request_changes(content_item_id):
    _, role = get_user_context()
    require_role(role, {"Approver"})
    get_json_body()  # optional note; not persisted
    with db.LOCK:
        ci = lookup.get_content(content_item_id)
        if ci["status"] != "IN_REVIEW":
            raise err(ERR_INVALID_STATE, "Content must be IN_REVIEW to request changes")
        ci["status"] = "CHANGES_REQUESTED"
        db.touch(ci)
        return response.ok(content_item_out(ci))


@bp.post("/content-items/<content_item_id>/resubmit")
def resubmit_content_item(content_item_id):
    _, role = get_user_context()
    require_role(role, {"ContentCreator"})
    with db.LOCK:
        ci = lookup.get_content(content_item_id)
        if ci["status"] != "CHANGES_REQUESTED":
            raise err(ERR_INVALID_STATE, "Content must be CHANGES_REQUESTED to resubmit")
        ci["status"] = "IN_REVIEW"
        ci["revision_round"] += 1
        db.touch(ci)
        return response.ok(content_item_out(ci))


@bp.post("/content-items/<content_item_id>/approve")
def approve_content_item(content_item_id):
    _, role = get_user_context()
    require_role(role, {"Approver"})
    with db.LOCK:
        ci = lookup.get_content(content_item_id)
        if ci["status"] != "IN_REVIEW":
            raise err(ERR_INVALID_STATE, "Content must be IN_REVIEW to approve")
        ci["status"] = "APPROVED"
        db.touch(ci)
        return response.ok(content_item_out(ci))


@bp.post("/content-items/<content_item_id>/schedule")
def schedule_content_item(content_item_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    body = get_json_body()
    with db.LOCK:
        ci = lookup.get_content(content_item_id)
        channel_id = require_string(body, "channel_id")
        channel = lookup.get_channel(channel_id)
        # cross-client: content item and channel must belong to same client
        if channel["client_id"] != ci["client_id"]:
            raise err(ERR_CROSS_CLIENT_REFERENCE,
                      "Channel and content item belong to different clients")
        if ci["status"] != "APPROVED":
            raise err(ERR_INVALID_STATE, "Content must be APPROVED to schedule")
        # channel must be LIVE and host one of the item's content targets
        if channel["status"] != "LIVE":
            raise err(ERR_CHANNEL_NOT_LIVE, "Target channel must be LIVE to schedule")
        hosts_target = any(
            t["content_item_id"] == content_item_id and t["channel_id"] == channel_id
            for t in db.content_targets.values()
        )
        if not hosts_target:
            raise err(ERR_INVALID_STATE,
                      "Channel does not host a content target of this item")
        slot_start = slot_geom.parse_utc(body.get("slot_start_utc"))
        duration = optional_int(body, "duration_minutes", 15)
        if duration < 1:
            raise err(ERR_INVALID_REQUEST, "duration_minutes must be >= 1")
        new_start = slot_start
        new_end = slot_start + timedelta(minutes=duration)
        # overlap + gap check against RESERVED/FIRED slots on the same channel
        gap_required = channel["min_publish_gap_minutes"]
        for s in db.schedule_slots.values():
            if s["channel_id"] != channel_id:
                continue
            if s["status"] not in ("RESERVED", "FIRED"):
                continue
            ex_start = slot_geom.parse_utc(s["slot_start_utc"])
            ex_end = ex_start + timedelta(minutes=s["duration_minutes"])
            if slot_geom.windows_overlap(new_start, new_end, ex_start, ex_end):
                raise err(ERR_SLOT_OVERLAP, "Slot overlaps an existing slot on the channel")
            if slot_geom.gap_minutes(new_start, new_end, ex_start, ex_end) < gap_required:
                raise err(ERR_SLOT_OVERLAP,
                          "Slot violates the channel's minimum publish gap")
        # reserve the slot
        slot = {
            "id": db.new_id(),
            "channel_id": channel_id,
            "content_item_id": content_item_id,
            "slot_start_utc": body.get("slot_start_utc"),
            "duration_minutes": duration,
            "status": "RESERVED",
        }
        db.stamp_create(slot, full=True)
        db.schedule_slots[slot["id"]] = slot
        ci["status"] = "SCHEDULED"
        ci["scheduled_slot_id"] = slot["id"]
        db.touch(ci)
        return response.ok(content_item_out(ci))


@bp.post("/content-items/<content_item_id>/unschedule")
def unschedule_content_item(content_item_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        ci = lookup.get_content(content_item_id)
        if ci["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "Content must be SCHEDULED to unschedule")
        slot = db.schedule_slots.get(ci.get("scheduled_slot_id"))
        if slot is not None and slot["status"] == "RESERVED":
            slot["status"] = "RELEASED"
            db.touch(slot)
        ci["status"] = "APPROVED"
        ci["scheduled_slot_id"] = None
        db.touch(ci)
        return response.ok(content_item_out(ci))


@bp.post("/content-items/<content_item_id>/publish")
def publish_content_item(content_item_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        ci = lookup.get_content(content_item_id)
        if ci["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "Content must be SCHEDULED to publish")
        client = lookup.get_client(ci["client_id"])
        published_count = count_posts_published_this_cycle(client)
        if published_count >= client["monthly_post_quota"]:
            raise err(ERR_POST_QUOTA_EXCEEDED,
                      "Monthly post quota reached for the current cycle")
        slot = db.schedule_slots.get(ci.get("scheduled_slot_id"))
        if slot is None or slot["status"] != "RESERVED":
            raise err(ERR_INVALID_STATE, "Reserved schedule slot is not RESERVED")
        # capture cycle, fire slot, fan out targets, bump quota counter
        ci["published_cycle_index"] = client["current_cycle_index"]
        ci["status"] = "PUBLISHED"
        slot["status"] = "FIRED"
        db.touch(slot)
        for t in db.content_targets.values():
            if t["content_item_id"] != content_item_id:
                continue
            ch = db.channels.get(t["channel_id"])
            if ch is not None and ch["status"] == "LIVE":
                t["publish_state"] = "PUBLISHED"
            else:
                t["publish_state"] = "SKIPPED"
            db.touch(t)
        db.touch(ci)
        # recompute the client's published tally for the current cycle
        client["posts_published_this_cycle"] = count_posts_published_this_cycle(client)
        return response.ok(content_item_out(ci))


@bp.post("/content-items/<content_item_id>/archive")
def archive_content_item(content_item_id):
    _, role = get_user_context()
    require_role(role, {"ContentCreator", "AccountManager"})
    with db.LOCK:
        ci = lookup.get_content(content_item_id)
        # Archive allowed from DRAFT, CHANGES_REQUESTED, APPROVED (never SCHEDULED).
        if ci["status"] not in ("DRAFT", "CHANGES_REQUESTED", "APPROVED"):
            raise err(ERR_INVALID_STATE,
                      "Content cannot be archived from its current state")
        ci["status"] = "ARCHIVED"
        db.touch(ci)
        return response.ok(content_item_out(ci))


# ---------------- Content targets ----------------

@bp.post("/content-targets")
def create_content_target():
    _, role = get_user_context()
    require_role(role, {"ContentCreator", "AccountManager"})
    body = get_json_body()
    content_item_id = require_string(body, "content_item_id")
    channel_id = require_string(body, "channel_id")
    with db.LOCK:
        # existence, validated in body order: content item then channel
        ci = lookup.get_content(content_item_id)
        channel = lookup.get_channel(channel_id)
        # cross-client: channel's client must equal content item's client
        if channel["client_id"] != ci["client_id"]:
            raise err(ERR_CROSS_CLIENT_REFERENCE,
                      "Channel and content item belong to different clients")
        t = {
            "id": db.new_id(),
            "content_item_id": content_item_id,
            "channel_id": channel_id,
            "publish_state": "PENDING",
        }
        db.stamp_create(t, full=True)
        db.content_targets[t["id"]] = t
        return response.created(content_target_out(t))


@bp.get("/content-targets")
def list_content_targets():
    _, role = get_user_context()
    require_role(role, {"ContentCreator", "AccountManager", "Approver", "PlatformAdmin"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.content_targets.values()), {
            "content_item_id": request.args.get("content_item_id"),
            "channel_id": request.args.get("channel_id"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([content_target_out(t) for t in window], limit, offset, total)


@bp.get("/content-targets/<target_id>")
def get_content_target(target_id):
    _, role = get_user_context()
    require_role(role, {"ContentCreator", "AccountManager", "Approver", "PlatformAdmin"})
    with db.LOCK:
        t = lookup.get_target(target_id)
        return response.ok(content_target_out(t))
