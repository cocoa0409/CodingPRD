"""Channel + schedule-slot read routes (PRD §3.2)."""
from flask import Blueprint, request

import db
import response
from errors import (
    err, ERR_INVALID_STATE, ERR_DUPLICATE_HANDLE, ERR_CHANNEL_LIMIT_EXCEEDED,
    ERR_CHANNEL_NOT_LIVE,
)
from middleware import (
    get_user_context, require_role, get_json_body, get_pagination,
    require_string, require_enum, optional_int,
)
from services import lookup, listing
from services.serialize import channel_out, schedule_slot_out

bp = Blueprint("channels", __name__)

PLATFORMS = {"FACEBOOK", "INSTAGRAM", "X", "LINKEDIN", "TIKTOK"}


@bp.post("/channels")
def create_channel():
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    body = get_json_body()
    client_id = require_string(body, "client_id")
    with db.LOCK:
        lookup.get_client(client_id)
        platform = require_enum(body, "platform", PLATFORMS)
        handle = require_string(body, "handle")
        gap = optional_int(body, "min_publish_gap_minutes", 30)
        if gap < 0:
            from errors import ERR_INVALID_REQUEST
            raise err(ERR_INVALID_REQUEST, "min_publish_gap_minutes must be >= 0")
        # Duplicate handle within (client_id, platform).
        for ch in db.channels.values():
            if ch["client_id"] == client_id and ch["platform"] == platform \
                    and ch["handle"] == handle:
                raise err(ERR_DUPLICATE_HANDLE,
                          "Handle already used for this client and platform")
        ch = {
            "id": db.new_id(),
            "client_id": client_id,
            "platform": platform,
            "handle": handle,
            "status": "PENDING",
            "min_publish_gap_minutes": gap,
        }
        db.stamp_create(ch, full=True)
        db.channels[ch["id"]] = ch
        return response.created(channel_out(ch))


@bp.get("/channels")
def list_channels():
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController", "CommunityAgent"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.channels.values()), {
            "client_id": request.args.get("client_id"),
            "status": request.args.get("status"),
            "platform": request.args.get("platform"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([channel_out(c) for c in window], limit, offset, total)


@bp.get("/channels/<channel_id>")
def get_channel(channel_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController", "CommunityAgent"})
    with db.LOCK:
        ch = lookup.get_channel(channel_id)
        return response.ok(channel_out(ch))


@bp.post("/channels/<channel_id>/connect")
def connect_channel(channel_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        ch = lookup.get_channel(channel_id)
        if ch["status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "Channel must be PENDING to connect")
        # cross-entity state: owning client must be ONBOARDING or ACTIVE
        client = lookup.get_client(ch["client_id"])
        if client["status"] not in ("ONBOARDING", "ACTIVE"):
            raise err(ERR_CHANNEL_NOT_LIVE,
                      "Owning client must be ONBOARDING or ACTIVE to connect a channel")
        ch["status"] = "CONNECTED"
        db.touch(ch)
        return response.ok(channel_out(ch))


@bp.post("/channels/<channel_id>/go-live")
def go_live_channel(channel_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        ch = lookup.get_channel(channel_id)
        if ch["status"] != "CONNECTED":
            raise err(ERR_INVALID_STATE, "Channel must be CONNECTED to go live")
        client = lookup.get_client(ch["client_id"])
        # cross-entity state guard: owning client not CHURNED (PRD §3.2)
        if client["status"] == "CHURNED":
            raise err(ERR_CHANNEL_NOT_LIVE, "Owning client is CHURNED")
        # channel limit: live count strictly fewer than package included_channels
        pkg = lookup.active_package_for_client(ch["client_id"])
        included = pkg["included_channels"] if pkg else 0
        live_count = sum(
            1 for c in db.channels.values()
            if c["client_id"] == ch["client_id"] and c["status"] == "LIVE"
        )
        if live_count >= included:
            raise err(ERR_CHANNEL_LIMIT_EXCEEDED,
                      "Going live would exceed included_channels")
        ch["status"] = "LIVE"
        db.touch(ch)
        return response.ok(channel_out(ch))


@bp.post("/channels/<channel_id>/disconnect")
def disconnect_channel(channel_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        ch = lookup.get_channel(channel_id)
        if ch["status"] not in ("PENDING", "CONNECTED", "LIVE"):
            raise err(ERR_INVALID_STATE, "Channel cannot be disconnected from its current state")
        ch["status"] = "DISCONNECTED"
        db.touch(ch)
        # cascade: release RESERVED slots; SCHEDULED content -> APPROVED
        for slot in db.schedule_slots.values():
            if slot["channel_id"] == channel_id and slot["status"] == "RESERVED":
                slot["status"] = "RELEASED"
                db.touch(slot)
                ci = db.content_items.get(slot["content_item_id"])
                if ci is not None and ci["status"] == "SCHEDULED":
                    ci["status"] = "APPROVED"
                    ci["scheduled_slot_id"] = None
                    db.touch(ci)
        return response.ok(channel_out(ch))


# ---- Schedule slots (read only; created indirectly via scheduling) ----

@bp.get("/schedule-slots")
def list_slots():
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.schedule_slots.values()), {
            "channel_id": request.args.get("channel_id"),
            "content_item_id": request.args.get("content_item_id"),
            "status": request.args.get("status"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([schedule_slot_out(s) for s in window], limit, offset, total)


@bp.get("/schedule-slots/<slot_id>")
def get_slot(slot_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    with db.LOCK:
        s = lookup.get_slot(slot_id)
        return response.ok(schedule_slot_out(s))
