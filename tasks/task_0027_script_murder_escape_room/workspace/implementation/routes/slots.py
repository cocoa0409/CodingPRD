"""Session slot routes (creation, list, get, start, complete, cancel)."""
from datetime import timedelta
from flask import Blueprint, request

from db import store, make_common, bump, parse_iso, fmt_iso, MATCH_CUTOFF_MINUTES
from middleware import require_role
from response import success_object, success_array
from validators import (
    get_json_body, require_string, require_int, optional_int, require_field,
    require_enum, optional_enum, require_list, optional_list,
    parse_pagination, paginate_list, sort_by_created_at,
)
from errors import (
    raise_error,
    ERR_VENUE_NOT_FOUND, ERR_ROOM_NOT_FOUND, ERR_THEME_NOT_FOUND, ERR_SLOT_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_VENUE_NOT_ACTIVE, ERR_INSUFFICIENT_PERMISSIONS,
    ERR_THEME_NOT_PUBLISHED, ERR_THEME_ROOM_INCOMPATIBLE,
)

slots_bp = Blueprint("slots", __name__)


VISIBILITIES = ["PRIVATE_ONLY", "PUBLIC_TEAMUP"]


def slot_view(s: dict) -> dict:
    return {
        "id": s["id"],
        "venue_id": s["venue_id"],
        "room_id": s["room_id"],
        "theme_id": s["theme_id"],
        "theme_version_pinned": s["theme_version_pinned"],
        "starts_at": s["starts_at"],
        "ends_at": s["ends_at"],
        "price_cents": s["price_cents"],
        "visibility": s["visibility"],
        "required_seats_for_launch": s["required_seats_for_launch"],
        "schedule_status": s["schedule_status"],
        "match_status": s["match_status"],
        "match_deadline_at": s["match_deadline_at"],
        "match_preferences": s.get("match_preferences"),
        "confirmed_seat_count": s["confirmed_seat_count"],
        "gross_revenue_cents": s["gross_revenue_cents"],
        "net_revenue_cents": s["net_revenue_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@slots_bp.route("/venues/<venue_id>/rooms/<room_id>/session-slots", methods=["POST"])
def create_slot(venue_id, room_id):
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
    theme_id = require_string(body, "theme_id")
    theme = store.themes.get(theme_id)
    if not theme:
        raise_error(ERR_THEME_NOT_FOUND, "theme not found")

    # Theme room-compatible check
    if room_id not in (theme.get("compatible_room_ids") or []):
        raise_error(ERR_THEME_ROOM_INCOMPATIBLE, "theme not compatible with room")

    # Theme published
    if theme["status"] != "PUBLISHED":
        raise_error(ERR_THEME_NOT_PUBLISHED, "theme not published")

    starts_at = require_string(body, "starts_at")
    try:
        ps = parse_iso(starts_at)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "invalid starts_at")
    duration_min = int(theme["duration_minutes"])
    pe = ps + timedelta(minutes=duration_min)

    visibility = require_enum(body, "visibility", VISIBILITIES)
    required_seats_for_launch = require_int(body, "required_seats_for_launch",
                                            theme["min_players"], theme["max_players"])
    price_cents = optional_int(body, "price_cents", 0, 100_000_000,
                               default=int(theme["base_price_cents"]))
    match_preferences = body.get("match_preferences")  # may be None

    # Overlap check
    from routes.venues import _check_overlap_for_proposed
    _check_overlap_for_proposed(r, fmt_iso(ps), fmt_iso(pe), "SLOT")

    match_deadline = ps - timedelta(minutes=MATCH_CUTOFF_MINUTES)

    s = make_common({
        "venue_id": venue_id,
        "room_id": room_id,
        "theme_id": theme_id,
        "theme_version_pinned": theme["current_version"],
        "starts_at": fmt_iso(ps),
        "ends_at": fmt_iso(pe),
        "price_cents": price_cents,
        "visibility": visibility,
        "required_seats_for_launch": required_seats_for_launch,
        "match_preferences": match_preferences,
        "schedule_status": "SCHEDULED",
        "match_status": "OPEN",
        "match_deadline_at": fmt_iso(match_deadline),
        "confirmed_seat_count": 0,
        "gross_revenue_cents": 0,
        "net_revenue_cents": 0,
    })
    store.session_slots[s["id"]] = s
    return success_object(slot_view(s), 201)


@slots_bp.route("/venues/<venue_id>/rooms/<room_id>/session-slots", methods=["GET"])
def list_room_slots(venue_id, room_id):
    require_role("PlatformAdmin", "VenueOperator", "Player")
    v = store.venues.get(venue_id)
    if not v:
        raise_error(ERR_VENUE_NOT_FOUND, "venue not found")
    r = store.rooms.get(room_id)
    if not r or r["venue_id"] != venue_id:
        raise_error(ERR_ROOM_NOT_FOUND, "room not found")
    limit, offset = parse_pagination()
    starts_after = request.args.get("starts_after")
    starts_before = request.args.get("starts_before")
    items = [s for s in store.session_slots.values() if s["room_id"] == room_id]
    if starts_after:
        try:
            sa = parse_iso(starts_after)
            items = [s for s in items if parse_iso(s["starts_at"]) >= sa]
        except Exception:
            raise_error(ERR_INVALID_REQUEST, "invalid starts_after")
    if starts_before:
        try:
            sb = parse_iso(starts_before)
            items = [s for s in items if parse_iso(s["starts_at"]) < sb]
        except Exception:
            raise_error(ERR_INVALID_REQUEST, "invalid starts_before")
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate_list(items, limit, offset)
    return success_array([slot_view(x) for x in page], limit, offset, total)


@slots_bp.route("/session-slots/<slot_id>", methods=["GET"])
def get_slot(slot_id):
    require_role("PlatformAdmin", "VenueOperator", "Player")
    s = store.session_slots.get(slot_id)
    if not s:
        raise_error(ERR_SLOT_NOT_FOUND, "slot not found")
    return success_object(slot_view(s))


@slots_bp.route("/session-slots/<slot_id>/start", methods=["POST"])
def start_slot_route(slot_id):
    user_id, role = require_role("VenueOperator")
    s = store.session_slots.get(slot_id)
    if not s:
        raise_error(ERR_SLOT_NOT_FOUND, "slot not found")
    v = store.venues.get(s["venue_id"])
    if user_id != v["id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    from services.slot_service import start_slot
    start_slot(s, user_id, role)
    return success_object(slot_view(s))


@slots_bp.route("/session-slots/<slot_id>/complete", methods=["POST"])
def complete_slot_route(slot_id):
    user_id, role = require_role("VenueOperator")
    s = store.session_slots.get(slot_id)
    if not s:
        raise_error(ERR_SLOT_NOT_FOUND, "slot not found")
    v = store.venues.get(s["venue_id"])
    if user_id != v["id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    from services.slot_service import complete_slot
    complete_slot(s, user_id, role)
    return success_object(slot_view(s))


@slots_bp.route("/session-slots/<slot_id>/cancel", methods=["POST"])
def cancel_slot_route(slot_id):
    user_id, role = require_role("VenueOperator")
    s = store.session_slots.get(slot_id)
    if not s:
        raise_error(ERR_SLOT_NOT_FOUND, "slot not found")
    v = store.venues.get(s["venue_id"])
    if user_id != v["id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    from services.slot_service import cancel_slot
    cancel_slot(s, "VENUE", user_id, role, trigger="operator")
    return success_object(slot_view(s))
