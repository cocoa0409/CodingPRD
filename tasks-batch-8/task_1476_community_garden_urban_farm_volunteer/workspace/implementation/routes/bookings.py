"""Group bookings with youth-supervision ratio enforcement (PRD section 3.6)."""
from datetime import timedelta
from math import ceil

from flask import Blueprint, request

import clock
import db
import services
from app_util import body
from errors import err, err_forbidden_role, err_invalid_request, err_not_found, err_ownership, err_state
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import pagination_args, req_int, req_list, req_str, require_field

bp = Blueprint("bookings", __name__)

CREATE_ROLES = ["GardenAdmin", "Coordinator", "GroupLeader"]
STAFF = ["GardenAdmin", "Coordinator"]
BOOKING_TARGETS = {"CONFIRMED", "REJECTED", "CHECKED_IN", "CANCELLED"}


def _get_booking(booking_id):
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise err_not_found("booking")
    return booking


def _ratio_check(member_count: int, minor_count: int, chaperone_count: int, chaperone_ids) -> None:
    """supervision_ratio_check: ceil(minor/8) chaperones, each listed chaperone
    (distinct ids) must hold an ACTIVE SUPERVISION cert."""
    required = ceil(minor_count / services.SUPERVISION_RATIO) if minor_count > 0 else 0
    certified = 0
    for vid in set(chaperone_ids):
        if db.volunteers.get(vid) is not None and services.has_active_cert(vid, "SUPERVISION"):
            certified += 1
    if not (chaperone_count >= required and certified >= required and minor_count <= member_count):
        raise err("ERR_SUPERVISION_RATIO_VIOLATION",
                  f"requires {required} chaperones with ACTIVE SUPERVISION certs")


def _check_slot_lock(slot):
    if not (clock.now() < slot["starts_at"] - timedelta(hours=24)):
        raise err("ERR_SLOT_LOCKED", "slot is locked (within 24h of start)")


@bp.post("/api/group-bookings")
def create_booking():
    ctx = require_auth()
    require_role(ctx, CREATE_ROLES)
    data = body()
    # existence (tier 3): slot, leader, then chaperone ids
    slot_id = require_field(data, "slot_id")
    slot = db.slots.get(slot_id)
    if slot is None:
        raise err_not_found("slot")
    leader_id = require_field(data, "leader_volunteer_id")
    leader = db.volunteers.get(leader_id)
    if leader is None:
        raise err_not_found("volunteer")
    chaperone_ids = data.get("chaperone_volunteer_ids")
    if chaperone_ids is None:
        chaperone_ids = []
    if not isinstance(chaperone_ids, list) or any(not isinstance(v, str) for v in chaperone_ids):
        raise err_invalid_request("chaperone_volunteer_ids must be an array of volunteer ids")
    for vid in chaperone_ids:
        if db.volunteers.get(vid) is None:
            raise err_not_found("volunteer")
    # ownership (tier 4): GroupLeader books only for itself
    if ctx.role == "GroupLeader" and ctx.user_id != leader_id:
        raise err_ownership()
    # shape (tier 5)
    org = req_str(data, "organization_name")
    member_count = req_int(data, "member_count")
    minor_count = req_int(data, "minor_count")
    chaperone_count = req_int(data, "chaperone_count")
    if member_count <= 0:
        raise err_invalid_request("member_count must be > 0")
    if minor_count < 0 or minor_count > member_count:
        raise err_invalid_request("minor_count must be >= 0 and <= member_count")
    if chaperone_count < 0:
        raise err_invalid_request("chaperone_count must be >= 0")
    # --- PRD 3.6 workflow gate sequence ---
    if slot["status"] not in {"OPEN", "FULL"}:
        raise err_state("SLOT")
    _check_slot_lock(slot)
    if leader["orientation_status"] != "ORIENTED":
        raise err("ERR_ORIENTATION_REQUIRED", "leader orientation_status is not ORIENTED")
    if leader["waiver_status"] != "SIGNED":
        raise err("ERR_WAIVER_REQUIRED", "leader waiver_status is not SIGNED")
    if leader["standing"] == "SUSPENDED":
        raise err("ERR_VOLUNTEER_SUSPENDED", "leader is SUSPENDED")
    _ratio_check(member_count, minor_count, chaperone_count, chaperone_ids)
    confirmed, youth, _ = services.slot_pools(slot_id)
    if confirmed + member_count > slot["capacity_total"]:
        raise err("ERR_SLOT_CAPACITY_EXCEEDED", "group exceeds slot capacity_total")
    if youth + minor_count > slot["capacity_youth"]:
        raise err("ERR_YOUTH_CAPACITY_EXCEEDED", "group minors exceed slot capacity_youth")
    rec = services.create_record({
        "slot_id": slot_id,
        "leader_volunteer_id": leader_id,
        "organization_name": org,
        "member_count": member_count,
        "minor_count": minor_count,
        "chaperone_count": chaperone_count,
        "chaperone_volunteer_ids": list(chaperone_ids),
        "required_chaperones": ceil(minor_count / services.SUPERVISION_RATIO) if minor_count > 0 else 0,
        "rejection_reason": None,
        "status": "REQUESTED",
    })
    db.bookings[rec["id"]] = rec
    return ok(services.booking_view(rec), status=201)


@bp.get("/api/group-bookings")
def list_bookings():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(
        db.bookings.values(),
        {"slot_id": "slot_id", "leader_volunteer_id": "leader_volunteer_id", "status": "status"},
        request.args, services.booking_view,
    )
    total = len(items)
    return ok([services.booking_view(b) for b in items[offset:offset + limit]],
              pagination=(limit, offset, total))


@bp.get("/api/group-bookings/<bookingId>")
def get_booking(bookingId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.booking_view(_get_booking(bookingId)))


@bp.post("/api/group-bookings/<bookingId>/transition")
def transition_booking(bookingId):
    ctx = require_auth()
    require_role(ctx, CREATE_ROLES)
    booking = _get_booking(bookingId)
    data = body()
    to_state = req_str(data, "to_state")
    if to_state not in BOOKING_TARGETS:
        raise err_invalid_request(f"to_state must be one of {sorted(BOOKING_TARGETS)}")
    # per-transition actors: CONFIRMED / REJECTED are staff-only
    if to_state in {"CONFIRMED", "REJECTED"} and ctx.role not in STAFF:
        raise err_forbidden_role()
    # ownership: GroupLeader acts only on its own bookings
    if ctx.role == "GroupLeader" and ctx.user_id != booking["leader_volunteer_id"]:
        raise err_ownership()
    slot = db.slots.get(booking["slot_id"])

    if to_state == "CONFIRMED":
        if booking["status"] != "REQUESTED":
            raise err_state("GROUP")
        if slot is None or slot["status"] not in {"OPEN", "FULL"}:
            raise err_state("SLOT")
        _check_slot_lock(slot)
        _ratio_check(booking["member_count"], booking["minor_count"],
                     booking["chaperone_count"], booking["chaperone_volunteer_ids"])
        confirmed, youth, _ = services.slot_pools(slot["id"])
        if confirmed + booking["member_count"] > slot["capacity_total"]:
            raise err("ERR_SLOT_CAPACITY_EXCEEDED", "group exceeds slot capacity_total")
        if youth + booking["minor_count"] > slot["capacity_youth"]:
            raise err("ERR_YOUTH_CAPACITY_EXCEEDED", "group minors exceed slot capacity_youth")
        booking["status"] = "CONFIRMED"
        services.bump(booking)
        services.recompute_slot_status(slot)

    elif to_state == "REJECTED":
        reason = data.get("rejection_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise err_invalid_request("rejection_reason must be non-empty")
        if booking["status"] != "REQUESTED":
            raise err_state("GROUP")
        booking["status"] = "REJECTED"
        booking["rejection_reason"] = reason
        services.bump(booking)

    elif to_state == "CHECKED_IN":
        if booking["status"] != "CONFIRMED":
            raise err_state("GROUP")
        now = clock.now()
        if not (slot["starts_at"] - timedelta(minutes=30) <= now <= slot["ends_at"]):
            raise err("ERR_OUTSIDE_CHECKIN_WINDOW",
                      "check-in window is [starts_at - 30min, ends_at]")
        booking["status"] = "CHECKED_IN"
        services.bump(booking)

    elif to_state == "CANCELLED":
        if booking["status"] not in {"REQUESTED", "CONFIRMED"}:
            raise err_state("GROUP")
        if booking["status"] == "CONFIRMED":
            _check_slot_lock(slot)
        booking["status"] = "CANCELLED"
        services.bump(booking)
        if slot is not None:
            services.recompute_slot_status(slot)

    return ok(services.booking_view(booking))
