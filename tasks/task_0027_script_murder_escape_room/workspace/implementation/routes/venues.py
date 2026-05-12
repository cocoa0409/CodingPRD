"""Venue and Room and MaintenanceWindow routes."""
from datetime import timedelta
from flask import Blueprint, request

from db import store, make_common, bump, parse_iso, fmt_iso
from middleware import require_role, get_user_context
from response import success_object, success_array
from validators import (
    get_json_body, require_string, require_int, optional_int, require_field,
    require_enum, require_list, optional_list, parse_pagination,
    check_optional_version, paginate_list, sort_by_created_at,
)
from errors import (
    raise_error,
    ERR_VENUE_NOT_FOUND, ERR_ROOM_NOT_FOUND, ERR_INVALID_REQUEST,
    ERR_VENUE_NOT_ACTIVE, ERR_VENUE_HAS_OPEN_SESSIONS, ERR_REVENUE_SPLIT_INVALID,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MAINTENANCE_OVERLAP_CONFLICT, ERR_SLOT_OVERLAP_CONFLICT,
)

venues_bp = Blueprint("venues", __name__)


def _venue_view(v: dict) -> dict:
    return {
        "id": v["id"],
        "chain_id": v["chain_id"],
        "name": v["name"],
        "timezone": v["timezone"],
        "business_hours": v["business_hours"],
        "deposit_policy_cents": v["deposit_policy_cents"],
        "revenue_share_bps": v["revenue_share_bps"],
        "author_royalty_bps": v["author_royalty_bps"],
        "host_commission_bps": v["host_commission_bps"],
        "platform_fee_bps": v["platform_fee_bps"],
        "status": v["status"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def _validate_business_hours(bh):
    if not isinstance(bh, dict):
        raise_error(ERR_INVALID_REQUEST, "business_hours must be object")
    for key, val in bh.items():
        if not isinstance(key, str) or key not in {"0", "1", "2", "3", "4", "5", "6"}:
            try:
                if int(key) not in range(0, 7):
                    raise_error(ERR_INVALID_REQUEST, "business_hours weekday key invalid")
            except Exception:
                raise_error(ERR_INVALID_REQUEST, "business_hours weekday key invalid")
        if val is None:
            continue
        if not isinstance(val, dict) or "open" not in val or "close" not in val:
            raise_error(ERR_INVALID_REQUEST, "business_hours value must be {open, close} or null")
        if not isinstance(val["open"], str) or not isinstance(val["close"], str):
            raise_error(ERR_INVALID_REQUEST, "business_hours open/close must be HH:MM strings")
        if val["open"] >= val["close"]:
            raise_error(ERR_INVALID_REQUEST, "business_hours: open must be < close")


def _check_revenue_split(rev_bps, author_bps, host_bps, platform_bps):
    s = int(rev_bps) + int(author_bps) + int(host_bps) + int(platform_bps)
    if s != 10000:
        raise_error(ERR_REVENUE_SPLIT_INVALID, "revenue_share+author+host+platform != 10000")


# ---- POST /venues ----
@venues_bp.route("/venues", methods=["POST"])
def create_venue():
    user_id, role = require_role("PlatformAdmin")
    body = get_json_body()
    chain_id = require_string(body, "chain_id", min_len=1, max_len=255)
    name = require_string(body, "name", min_len=1, max_len=120)
    timezone = body.get("timezone") or "Asia/Shanghai"
    if not isinstance(timezone, str):
        raise_error(ERR_INVALID_REQUEST, "timezone must be string")
    business_hours = require_field(body, "business_hours")
    _validate_business_hours(business_hours)
    deposit_policy_cents = require_int(body, "deposit_policy_cents", 0, 1_000_000)
    revenue_share_bps = require_int(body, "revenue_share_bps", 0, 10000)
    author_royalty_bps = require_int(body, "author_royalty_bps", 0, 10000)
    host_commission_bps = require_int(body, "host_commission_bps", 0, 10000)
    platform_fee_bps = require_int(body, "platform_fee_bps", 0, 10000)
    _check_revenue_split(revenue_share_bps, author_royalty_bps, host_commission_bps, platform_fee_bps)

    # Uniqueness within chain
    for v in store.venues.values():
        if v["chain_id"] == chain_id and v["name"] == name:
            raise_error(ERR_INVALID_REQUEST, "venue name not unique within chain")

    v = make_common({
        "chain_id": chain_id,
        "name": name,
        "timezone": timezone,
        "business_hours": business_hours,
        "deposit_policy_cents": deposit_policy_cents,
        "revenue_share_bps": revenue_share_bps,
        "author_royalty_bps": author_royalty_bps,
        "host_commission_bps": host_commission_bps,
        "platform_fee_bps": platform_fee_bps,
        "status": "ACTIVE",
    })
    store.venues[v["id"]] = v
    return success_object(_venue_view(v), 201)


@venues_bp.route("/venues", methods=["GET"])
def list_venues():
    require_role("PlatformAdmin", "VenueOperator", "Player")
    limit, offset = parse_pagination()
    chain_id = request.args.get("chain_id")
    items = list(store.venues.values())
    if chain_id:
        items = [v for v in items if v["chain_id"] == chain_id]
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate_list(items, limit, offset)
    return success_array([_venue_view(v) for v in page], limit, offset, total)


@venues_bp.route("/venues/<venue_id>", methods=["GET"])
def get_venue(venue_id):
    require_role("PlatformAdmin", "VenueOperator", "Player")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    return success_object(_venue_view(v))


@venues_bp.route("/venues/<venue_id>", methods=["PATCH"])
def patch_venue(venue_id):
    require_role("PlatformAdmin")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    body = get_json_body()
    check_optional_version(body, v)

    if "business_hours" in body and body["business_hours"] is not None:
        _validate_business_hours(body["business_hours"])
        v["business_hours"] = body["business_hours"]
    if "deposit_policy_cents" in body and body["deposit_policy_cents"] is not None:
        v["deposit_policy_cents"] = require_int(body, "deposit_policy_cents", 0, 1_000_000)
    for f in ("revenue_share_bps", "author_royalty_bps", "host_commission_bps", "platform_fee_bps"):
        if f in body and body[f] is not None:
            v[f] = require_int(body, f, 0, 10000)
    _check_revenue_split(v["revenue_share_bps"], v["author_royalty_bps"],
                         v["host_commission_bps"], v["platform_fee_bps"])
    bump(v)
    return success_object(_venue_view(v))


@venues_bp.route("/venues/<venue_id>/suspend", methods=["POST"])
def suspend_venue(venue_id):
    user_id, role = require_role("PlatformAdmin")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    if v["status"] != "ACTIVE":
        raise_error(ERR_INVALID_REQUEST, "venue not in ACTIVE")
    v["status"] = "SUSPENDED"
    bump(v)
    # Cascade-cancel SCHEDULED slots
    from services.slot_service import cancel_slot
    for slot in list(store.session_slots.values()):
        if slot["venue_id"] == venue_id and slot["schedule_status"] == "SCHEDULED":
            cancel_slot(slot, "VENUE", user_id, role, trigger="venue_suspend")
    return success_object(_venue_view(v))


@venues_bp.route("/venues/<venue_id>/resume", methods=["POST"])
def resume_venue(venue_id):
    require_role("PlatformAdmin")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    if v["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_REQUEST, "venue not SUSPENDED")
    v["status"] = "ACTIVE"
    bump(v)
    return success_object(_venue_view(v))


@venues_bp.route("/venues/<venue_id>/close", methods=["POST"])
def close_venue(venue_id):
    require_role("PlatformAdmin")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    if v["status"] == "CLOSED":
        raise_error(ERR_INVALID_REQUEST, "venue already CLOSED")
    # Reject if any open sessions
    for slot in store.session_slots.values():
        if slot["venue_id"] == venue_id and slot["schedule_status"] in ("SCHEDULED", "LIVE"):
            raise_error(ERR_VENUE_HAS_OPEN_SESSIONS, "venue has open sessions")
    v["status"] = "CLOSED"
    bump(v)
    return success_object(_venue_view(v))


# =========================================================
# Rooms
# =========================================================
def _room_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "venue_id": r["venue_id"],
        "name": r["name"],
        "capacity_min": r["capacity_min"],
        "capacity_max": r["capacity_max"],
        "turnover_minutes": r["turnover_minutes"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@venues_bp.route("/venues/<venue_id>/rooms", methods=["POST"])
def create_room(venue_id):
    user_id, role = require_role("VenueOperator")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    # Ownership: VenueOperator's X-User-ID must equal venue.id
    if user_id != v["id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    if v["status"] != "ACTIVE":
        raise_error(ERR_VENUE_NOT_ACTIVE, "venue not active")
    body = get_json_body()
    name = require_string(body, "name", 1, 200)
    capacity_min = require_int(body, "capacity_min", 1, 20)
    capacity_max = require_int(body, "capacity_max", capacity_min, 20)
    turnover_minutes = optional_int(body, "turnover_minutes", 0, 240, default=30)
    # uniqueness within venue
    for r in store.rooms.values():
        if r["venue_id"] == venue_id and r["name"] == name:
            raise_error(ERR_INVALID_REQUEST, "room name not unique in venue")
    r = make_common({
        "venue_id": venue_id,
        "name": name,
        "capacity_min": capacity_min,
        "capacity_max": capacity_max,
        "turnover_minutes": turnover_minutes,
        "status": "ACTIVE",
    })
    store.rooms[r["id"]] = r
    return success_object(_room_view(r), 201)


@venues_bp.route("/venues/<venue_id>/rooms", methods=["GET"])
def list_rooms(venue_id):
    require_role("PlatformAdmin", "VenueOperator", "Player")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    limit, offset = parse_pagination()
    items = sort_by_created_at([r for r in store.rooms.values() if r["venue_id"] == venue_id])
    total = len(items)
    page = paginate_list(items, limit, offset)
    return success_array([_room_view(r) for r in page], limit, offset, total)


@venues_bp.route("/venues/<venue_id>/rooms/<room_id>", methods=["GET"])
def get_room(venue_id, room_id):
    require_role("PlatformAdmin", "VenueOperator", "Player")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    r = store.rooms.get(room_id)
    if not r or r["venue_id"] != venue_id:
        raise_error(ERR_ROOM_NOT_FOUND, "room not found")
    return success_object(_room_view(r))


# =========================================================
# Maintenance windows
# =========================================================
def _mw_view(mw: dict) -> dict:
    return {
        "id": mw["id"],
        "room_id": mw["room_id"],
        "starts_at": mw["starts_at"],
        "ends_at": mw["ends_at"],
        "reason": mw.get("reason"),
        "status": mw["status"],
        "created_at": mw["created_at"],
        "updated_at": mw["updated_at"],
        "version": mw["version"],
    }


def _check_overlap_for_proposed(room: dict, p_start_iso: str, p_end_iso: str,
                                proposed_kind: str,
                                ignore_slot_id: str | None = None,
                                ignore_mw_id: str | None = None):
    """Check overlap; raises slot vs maintenance conflict error appropriately.
    proposed_kind: 'SLOT' or 'MAINTENANCE'.
    """
    p_start = parse_iso(p_start_iso)
    p_end = parse_iso(p_end_iso)
    turnover = timedelta(minutes=int(room.get("turnover_minutes", 30)))

    if proposed_kind == "SLOT":
        p_finish = p_end + turnover
    else:
        p_finish = p_end

    # Existing slots on same room
    for s in store.session_slots.values():
        if s["room_id"] != room["id"]:
            continue
        if ignore_slot_id and s["id"] == ignore_slot_id:
            continue
        if s["schedule_status"] not in ("SCHEDULED", "LIVE"):
            continue
        x_start = parse_iso(s["starts_at"])
        x_end = parse_iso(s["ends_at"])
        x_finish = x_end + turnover  # slots get turnover applied
        if max(p_start, x_start) < min(p_finish, x_finish):
            if proposed_kind == "SLOT":
                raise_error(ERR_SLOT_OVERLAP_CONFLICT, "slot overlaps with slot")
            else:
                raise_error(ERR_MAINTENANCE_OVERLAP_CONFLICT, "maintenance overlaps with slot")

    # Existing maintenance windows on same room
    for mw in store.maintenance_windows.values():
        if mw["room_id"] != room["id"]:
            continue
        if ignore_mw_id and mw["id"] == ignore_mw_id:
            continue
        if mw["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        x_start = parse_iso(mw["starts_at"])
        x_end = parse_iso(mw["ends_at"])
        # For maintenance existing items, finish = its own ends_at (no turnover)
        x_finish = x_end
        if max(p_start, x_start) < min(p_finish, x_finish):
            if proposed_kind == "SLOT":
                raise_error(ERR_SLOT_OVERLAP_CONFLICT, "slot overlaps with maintenance")
            else:
                raise_error(ERR_MAINTENANCE_OVERLAP_CONFLICT, "maintenance overlaps with maintenance")


@venues_bp.route("/venues/<venue_id>/rooms/<room_id>/maintenance-windows", methods=["POST"])
def create_maintenance(venue_id, room_id):
    user_id, role = require_role("VenueOperator")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    r = store.rooms.get(room_id)
    if not r or r["venue_id"] != venue_id:
        raise_error(ERR_ROOM_NOT_FOUND, "room not found")
    if user_id != v["id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    if v["status"] != "ACTIVE":
        raise_error(ERR_VENUE_NOT_ACTIVE, "venue not active")
    body = get_json_body()
    starts_at = require_string(body, "starts_at")
    ends_at = require_string(body, "ends_at")
    try:
        ps = parse_iso(starts_at)
        pe = parse_iso(ends_at)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "invalid timestamp")
    if pe <= ps:
        raise_error(ERR_INVALID_REQUEST, "ends_at must be > starts_at")
    reason = body.get("reason") or ""

    _check_overlap_for_proposed(r, fmt_iso(ps), fmt_iso(pe), "MAINTENANCE")

    mw = make_common({
        "room_id": room_id,
        "starts_at": fmt_iso(ps),
        "ends_at": fmt_iso(pe),
        "reason": reason,
        "status": "SCHEDULED",
    })
    store.maintenance_windows[mw["id"]] = mw
    return success_object(_mw_view(mw), 201)


@venues_bp.route("/venues/<venue_id>/rooms/<room_id>/maintenance-windows", methods=["GET"])
def list_maintenance(venue_id, room_id):
    require_role("PlatformAdmin", "VenueOperator", "Player")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    r = store.rooms.get(room_id)
    if not r or r["venue_id"] != venue_id:
        raise_error(ERR_ROOM_NOT_FOUND, "room not found")
    limit, offset = parse_pagination()
    items = sort_by_created_at([m for m in store.maintenance_windows.values()
                                if m["room_id"] == room_id])
    total = len(items)
    page = paginate_list(items, limit, offset)
    return success_array([_mw_view(m) for m in page], limit, offset, total)
