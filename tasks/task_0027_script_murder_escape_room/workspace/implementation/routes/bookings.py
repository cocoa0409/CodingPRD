"""Booking & waitlist routes."""
from flask import Blueprint, request

from db import store, make_common, bump, parse_iso, NO_SHOW_BAN_THRESHOLD
from middleware import require_role, get_user_context
from response import success_object, success_array
from validators import (
    get_json_body, require_string, require_int, optional_int,
    require_field, require_list, parse_pagination,
    paginate_list, sort_by_created_at,
)
from errors import (
    raise_error,
    ERR_SLOT_NOT_FOUND, ERR_BOOKING_NOT_FOUND, ERR_WAITLIST_ENTRY_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_INSUFFICIENT_PERMISSIONS, ERR_VENUE_NOT_ACTIVE,
    ERR_PLAYER_BANNED, ERR_MATCH_PREFERENCE_REJECTED, ERR_SLOT_FULL,
    ERR_PLAYER_NOT_FOUND, ERR_BOOKING_NOT_CANCELLABLE_BY_PLAYER,
    ERR_SESSION_NOT_OPEN_FOR_CANCEL, ERR_SESSION_NOT_LIVE,
    ERR_SESSION_NOT_OPEN_FOR_CONFIRM,
)
from services import booking_service, slot_service

bookings_bp = Blueprint("bookings", __name__)


def booking_view(b: dict) -> dict:
    return {
        "id": b["id"],
        "slot_id": b["slot_id"],
        "lead_player_id": b["lead_player_id"],
        "team_player_ids": b["team_player_ids"],
        "seat_count": b["seat_count"],
        "paid_amount_cents": b["paid_amount_cents"],
        "deposit_held_cents": b["deposit_held_cents"],
        "refund_total_cents": b["refund_total_cents"],
        "cancellation_initiator": b.get("cancellation_initiator"),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def waitlist_view(w: dict) -> dict:
    return {
        "id": w["id"],
        "slot_id": w["slot_id"],
        "lead_player_id": w["lead_player_id"],
        "requested_seat_count": w["requested_seat_count"],
        "priority_class": w["priority_class"],
        "enqueued_at": w["enqueued_at"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def _check_match_preferences(slot: dict, player: dict):
    """PRD §3.5 says match_preferences is a payload "structured around gender,
    age range, and experience-level filters" but does not pin its key names.
    Accept the natural variants so callers can use whichever spelling matches
    their conventions."""
    prefs = slot.get("match_preferences")
    if not prefs or slot["visibility"] != "PUBLIC_TEAMUP":
        return
    if not isinstance(prefs, dict):
        return
    # gender filter
    g_allowed = prefs.get("genders") or prefs.get("gender_allowed") or prefs.get("gender_filter")
    if g_allowed and player.get("gender") not in g_allowed:
        raise_error(ERR_MATCH_PREFERENCE_REJECTED, "gender preference rejected")
    # age range
    age_min = prefs.get("age_min") if prefs.get("age_min") is not None else prefs.get("min_age")
    age_max = prefs.get("age_max") if prefs.get("age_max") is not None else prefs.get("max_age")
    if age_min is not None and player["age"] < age_min:
        raise_error(ERR_MATCH_PREFERENCE_REJECTED, "age below min")
    if age_max is not None and player["age"] > age_max:
        raise_error(ERR_MATCH_PREFERENCE_REJECTED, "age above max")
    # experience filter
    exp_allowed = (
        prefs.get("experience_levels")
        or prefs.get("experience_level_allowed")
        or prefs.get("experience_levels_allowed")
    )
    if exp_allowed and player.get("experience_level") not in exp_allowed:
        raise_error(ERR_MATCH_PREFERENCE_REJECTED, "experience preference rejected")


# =========================================================
# Bookings
# =========================================================
@bookings_bp.route("/session-slots/<slot_id>/bookings", methods=["POST"])
def create_booking(slot_id):
    user_id, role = require_role("Player")
    slot = store.session_slots.get(slot_id)
    if not slot:
        raise_error(ERR_SLOT_NOT_FOUND, "slot not found")
    venue = store.venues.get(slot["venue_id"])
    if not venue or venue["status"] != "ACTIVE":
        raise_error(ERR_VENUE_NOT_ACTIVE, "venue not active")
    if slot["schedule_status"] != "SCHEDULED":
        raise_error(ERR_SESSION_NOT_OPEN_FOR_CONFIRM, "slot not SCHEDULED")

    body = get_json_body()
    team_player_ids = require_list(body, "team_player_ids")
    if not team_player_ids:
        raise_error(ERR_INVALID_REQUEST, "team_player_ids must be non-empty")
    for pid in team_player_ids:
        if not isinstance(pid, str):
            raise_error(ERR_INVALID_REQUEST, "team_player_ids must be string ids")
    if user_id not in team_player_ids:
        raise_error(ERR_INVALID_REQUEST, "lead player must be in team_player_ids")

    # Player ownership: lead is X-User-ID
    player = store.players.get(user_id)
    if not player:
        raise_error(ERR_PLAYER_NOT_FOUND, "player not found")
    # Validate every team player exists
    for pid in team_player_ids:
        if pid not in store.players:
            raise_error(ERR_PLAYER_NOT_FOUND, "team player not found")

    # Player banned check
    if player.get("status") == "BANNED" or int(player.get("no_show_strikes", 0)) >= NO_SHOW_BAN_THRESHOLD:
        raise_error(ERR_PLAYER_BANNED, "player banned")

    # Match preferences (PUBLIC_TEAMUP)
    if slot["visibility"] == "PUBLIC_TEAMUP":
        for pid in team_player_ids:
            p = store.players[pid]
            _check_match_preferences(slot, p)

    seat_count = len(team_player_ids)
    theme = store.themes[slot["theme_id"]]
    if slot["confirmed_seat_count"] + seat_count > theme["max_players"]:
        raise_error(ERR_SLOT_FULL, "would exceed max_players")

    paid_amount = seat_count * slot["price_cents"]
    deposit_held = seat_count * venue["deposit_policy_cents"]

    b = make_common({
        "slot_id": slot_id,
        "lead_player_id": user_id,
        "team_player_ids": list(team_player_ids),
        "seat_count": seat_count,
        "paid_amount_cents": paid_amount,
        "deposit_held_cents": deposit_held,
        "refund_total_cents": 0,
        "cancellation_initiator": None,
        "status": "PENDING_DEPOSIT",
    })
    store.bookings[b["id"]] = b
    return success_object(booking_view(b), 201)


@bookings_bp.route("/bookings/<booking_id>/confirm-deposit", methods=["POST"])
def confirm_deposit(booking_id):
    user_id, role = require_role("Player", "PaymentGateway")
    b = store.bookings.get(booking_id)
    if not b:
        raise_error(ERR_BOOKING_NOT_FOUND, "booking not found")
    if role == "Player" and user_id != b["lead_player_id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own booking")
    body = get_json_body()
    idem = body.get("idempotency_key")
    booking_service.confirm_booking_deposit(b, user_id, role, idem)
    return success_object(booking_view(b))


@bookings_bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking_route(booking_id):
    user_id, role = require_role("Player", "VenueOperator")
    b = store.bookings.get(booking_id)
    if not b:
        raise_error(ERR_BOOKING_NOT_FOUND, "booking not found")
    slot = store.session_slots[b["slot_id"]]
    if role == "Player":
        if user_id != b["lead_player_id"]:
            raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own booking")
        if slot["schedule_status"] != "SCHEDULED":
            if slot["schedule_status"] in ("LIVE", "COMPLETED"):
                raise_error(ERR_BOOKING_NOT_CANCELLABLE_BY_PLAYER, "slot already past SCHEDULED")
            else:
                raise_error(ERR_SESSION_NOT_OPEN_FOR_CANCEL, "slot not open for cancel")
        if b["status"] not in ("PENDING_DEPOSIT", "CONFIRMED"):
            raise_error(ERR_INVALID_REQUEST, "booking not cancellable from current status")
        booking_service.cancel_booking(b, "PLAYER", user_id, role)
    else:  # VenueOperator
        v = store.venues.get(slot["venue_id"])
        if user_id != v["id"]:
            raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
        if b["status"] not in ("PENDING_DEPOSIT", "CONFIRMED"):
            raise_error(ERR_INVALID_REQUEST, "booking not cancellable from current status")
        booking_service.cancel_booking(b, "VENUE", user_id, role)
    return success_object(booking_view(b))


@bookings_bp.route("/bookings/<booking_id>/check-in", methods=["POST"])
def check_in_route(booking_id):
    user_id, role = require_role("VenueOperator")
    b = store.bookings.get(booking_id)
    if not b:
        raise_error(ERR_BOOKING_NOT_FOUND, "booking not found")
    slot = store.session_slots[b["slot_id"]]
    v = store.venues.get(slot["venue_id"])
    if user_id != v["id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    slot_service.check_in_booking(b, user_id, role)
    return success_object(booking_view(b))


@bookings_bp.route("/bookings/<booking_id>/refund", methods=["POST"])
def refund_route(booking_id):
    user_id, role = require_role("VenueOperator")
    b = store.bookings.get(booking_id)
    if not b:
        raise_error(ERR_BOOKING_NOT_FOUND, "booking not found")
    slot = store.session_slots[b["slot_id"]]
    v = store.venues.get(slot["venue_id"])
    if user_id != v["id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    body = get_json_body()
    refund_amount = require_int(body, "refund_amount_cents", 0, 1_000_000_000)
    booking_service.refund_booking(b, refund_amount, user_id, role)
    return success_object(booking_view(b))


@bookings_bp.route("/bookings/<booking_id>", methods=["GET"])
def get_booking_route(booking_id):
    user_id, role = require_role("Player", "VenueOperator", "PlatformAdmin")
    b = store.bookings.get(booking_id)
    if not b:
        raise_error(ERR_BOOKING_NOT_FOUND, "booking not found")
    if role == "Player":
        if user_id != b["lead_player_id"]:
            raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own booking")
    elif role == "VenueOperator":
        slot = store.session_slots[b["slot_id"]]
        v = store.venues.get(slot["venue_id"])
        if not v or user_id != v["id"]:
            raise_error(ERR_INSUFFICIENT_PERMISSIONS, "venue ownership mismatch")
    return success_object(booking_view(b))


# =========================================================
# Waitlist
# =========================================================
@bookings_bp.route("/session-slots/<slot_id>/waitlist-entries", methods=["POST"])
def enqueue_waitlist(slot_id):
    user_id, role = require_role("Player")
    slot = store.session_slots.get(slot_id)
    if not slot:
        raise_error(ERR_SLOT_NOT_FOUND, "slot not found")
    if slot["schedule_status"] != "SCHEDULED":
        raise_error(ERR_INVALID_REQUEST, "slot not open for waitlist")
    venue = store.venues.get(slot["venue_id"])
    if venue["status"] != "ACTIVE":
        raise_error(ERR_VENUE_NOT_ACTIVE, "venue not active")
    player = store.players.get(user_id)
    if not player:
        raise_error(ERR_PLAYER_NOT_FOUND, "player not found")
    if player.get("status") == "BANNED" or int(player.get("no_show_strikes", 0)) >= NO_SHOW_BAN_THRESHOLD:
        raise_error(ERR_PLAYER_BANNED, "player banned")

    body = get_json_body()
    theme = store.themes[slot["theme_id"]]
    requested_seat_count = require_int(body, "requested_seat_count", 1, theme["max_players"])

    from db import now_iso
    w = make_common({
        "slot_id": slot_id,
        "lead_player_id": user_id,
        "requested_seat_count": requested_seat_count,
        "priority_class": "VIP" if player.get("tier") == "VIP" else "STANDARD",
        "enqueued_at": now_iso(),
        "status": "QUEUED",
    })
    store.waitlist_entries[w["id"]] = w
    return success_object(waitlist_view(w), 201)


@bookings_bp.route("/waitlist-entries/<entry_id>/cancel", methods=["POST"])
def cancel_waitlist(entry_id):
    user_id, role = require_role("Player")
    w = store.waitlist_entries.get(entry_id)
    if not w:
        raise_error(ERR_WAITLIST_ENTRY_NOT_FOUND, "entry not found")
    if user_id != w["lead_player_id"]:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS, "not own waitlist entry")
    if w["status"] != "QUEUED":
        raise_error(ERR_INVALID_REQUEST, "entry not QUEUED")
    w["status"] = "CANCELLED"
    bump(w)
    return success_object(waitlist_view(w))


@bookings_bp.route("/session-slots/<slot_id>/waitlist-entries", methods=["GET"])
def list_waitlist(slot_id):
    user_id, role = require_role("Player", "VenueOperator")
    slot = store.session_slots.get(slot_id)
    if not slot:
        raise_error(ERR_SLOT_NOT_FOUND, "slot not found")
    limit, offset = parse_pagination()
    items = sort_by_created_at([w for w in store.waitlist_entries.values()
                                if w["slot_id"] == slot_id])
    total = len(items)
    page = paginate_list(items, limit, offset)
    return success_array([waitlist_view(w) for w in page], limit, offset, total)
