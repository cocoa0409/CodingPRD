"""The event booking lifecycle: draft, hold, commitment, release and the sweep."""

from flask import Blueprint

import calc
import cascade
import serial
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from routes_venue import get_venue
from store import db, now_logical, ordered, stamp_new, touch

bp = Blueprint("bookings", __name__)

LIVE_STATES = ("HELD", "CHALLENGED", "CONFIRMED")
RELEASABLE_STATES = ("DRAFT", "HELD", "CHALLENGED", "CONFIRMED")


def get_booking(booking_id):
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND")
    return booking


def _half_open_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.post("/event-bookings")
def create_booking():
    user_id, role = v.auth(("BookingManager", "AnchorTenantRep"))
    payload = v.body()

    # Ladder 3: an AnchorTenantRep may only draft for its own tenant.
    if role == "AnchorTenantRep" and payload.get("tenant_id") != user_id:
        raise ApiError("ERR_TENANT_SCOPE_VIOLATION")

    # Ladder 5: request shape.
    venue_id = v.req_id(payload, "venue_id")
    profile_id = v.req_id(payload, "config_profile_id")
    tenant_id = v.opt_id(payload, "tenant_id")
    title = v.req_str(payload, "title", 1, 160)
    start = v.req_dt(payload, "event_start_utc")
    end = v.req_dt(payload, "event_end_utc")
    if end <= start:
        v.bad("event_end_utc must be strictly after event_start_utc.")
    expected_attendance = v.req_int(payload, "expected_attendance", 0)
    rigging_load = v.opt_num(payload, "rigging_load_kg", 0, 0)
    promoter_name = v.opt_str(payload, "promoter_name", None, 1, 160)
    if tenant_id is None and promoter_name is None:
        v.bad("promoter_name is required when tenant_id is absent.")

    # Ladder 7: existence, body identifiers in declaration order.
    venue = get_venue(venue_id)
    profile = db.profiles.get(profile_id)
    if profile is None:
        raise ApiError("ERR_PROFILE_NOT_FOUND")
    tenant = None
    if tenant_id is not None:
        tenant = db.tenants.get(tenant_id)
        if tenant is None:
            raise ApiError("ERR_TENANT_NOT_FOUND")

    # Ladder 5, deferred because it reads the resolved profile.
    if expected_attendance > int(profile["nominal_seats"]):
        v.bad("expected_attendance may not exceed the profile's nominal_seats.")

    # Ladder 17: referential scoping.
    if profile["venue_id"] != venue["id"]:
        raise ApiError("ERR_VENUE_SCOPE_MISMATCH")
    if tenant is not None and tenant["venue_id"] != venue["id"]:
        raise ApiError("ERR_VENUE_SCOPE_MISMATCH")

    row = {
        "venue_id": venue["id"],
        "tenant_id": tenant["id"] if tenant is not None else None,
        "config_profile_id": profile["id"],
        "displaced_by_booking_id": None,
        "title": title,
        "promoter_name": promoter_name,
        "event_start_utc": start,
        "event_end_utc": end,
        "rigging_load_kg": rigging_load,
        "expected_attendance": expected_attendance,
        "status": "DRAFT",
        "hold_tier": None,
        "hold_placed_at": None,
        "hold_expires_at": None,
        "release_reason": None,
        "displacement_penalty_cents": 0,
    }
    stamp_new(row)
    db.bookings[row["id"]] = row
    return created(serial.booking(row))


@bp.get("/event-bookings/<booking_id>")
def read_booking(booking_id):
    v.auth(v.ALL_ROLES)
    return ok(serial.booking(get_booking(booking_id)))


@bp.get("/event-bookings")
def list_bookings():
    v.auth(v.ALL_ROLES)
    limit, offset = v.pagination()
    matched = list(db.bookings.values())
    for arg, field in (("venue_id", "venue_id"),
                       ("tenant_id", "tenant_id"),
                       ("config_profile_id", "config_profile_id"),
                       ("displaced_by_booking_id", "displaced_by_booking_id"),
                       ("status", "status")):
        value = v.filter_arg(arg)
        if value is not None:
            matched = [b for b in matched if b[field] == value]
    matched = ordered(matched)
    page, total = v.paginate(matched, limit, offset)
    return ok_list([serial.booking(b) for b in page], limit, offset, total)


@bp.post("/event-bookings/<booking_id>/hold")
def place_hold(booking_id):
    user_id, role = v.auth(("BookingManager", "AnchorTenantRep"))
    booking = get_booking(booking_id)

    # Ladder 3: tenant ownership scope.
    if role == "AnchorTenantRep" and booking["tenant_id"] != user_id:
        raise ApiError("ERR_TENANT_SCOPE_VIOLATION")

    # Ladder 9: from-state legality.
    if booking["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_BOOKING_STATE")

    tenant = db.tenants.get(booking["tenant_id"]) if booking["tenant_id"] else None
    # Ladder 18: fiscal capacity, last.
    if tenant is not None:
        if calc.holds_consumed(tenant["id"]) >= int(tenant["guaranteed_holds_per_season"]):
            raise ApiError("ERR_TENANT_HOLD_QUOTA_EXCEEDED")

    placed_at = now_logical()
    tier = tenant["hold_priority_tier"] if tenant is not None else "OPEN"
    booking["hold_placed_at"] = placed_at
    booking["hold_tier"] = tier
    booking["hold_expires_at"] = calc.hold_expires_at(placed_at, tier)
    booking["status"] = "HELD"
    touch(booking)
    venue = db.venues.get(booking["venue_id"])
    if venue is not None:
        cascade.bump_venue(venue)
    return ok(serial.booking(booking))


@bp.post("/event-bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    v.auth(("BookingManager",))
    payload = v.body()
    # Ladder 5: shape.
    expected_version = v.plain_int(payload, "expected_venue_version")
    # Ladder 7: existence.
    booking = get_booking(booking_id)
    venue = db.venues.get(booking["venue_id"])
    # Ladder 8: optimistic concurrency on the arena record.
    if venue is None or int(venue["version"]) != int(expected_version):
        raise ApiError("ERR_STALE_VENUE_VERSION")
    # Ladder 9: from-state legality.
    if booking["status"] != "HELD":
        raise ApiError("ERR_INVALID_BOOKING_STATE")
    # Ladder 15: temporal feasibility — interval conflict, then hold expiry.
    for peer in db.bookings.values():
        if peer["id"] == booking["id"] or peer["venue_id"] != booking["venue_id"]:
            continue
        if peer["status"] != "CONFIRMED":
            continue
        if _half_open_overlap(booking["event_start_utc"], booking["event_end_utc"],
                              peer["event_start_utc"], peer["event_end_utc"]):
            raise ApiError("ERR_BOOKING_TIME_CONFLICT")
    if booking["hold_expires_at"] is not None and now_logical() > booking["hold_expires_at"]:
        raise ApiError("ERR_HOLD_EXPIRED")
    # Ladder 18: fiscal capacity — the roof grid aggregate.
    peer_load = calc.rigging_peer_load(booking["venue_id"], booking["event_start_utc"],
                                       booking["event_end_utc"], booking["id"])
    total = calc.round_half_up(peer_load + calc.dec(booking["rigging_load_kg"]), 2)
    if total > calc.dec(venue["rigging_capacity_kg"]):
        raise ApiError("ERR_RIGGING_CAPACITY_EXCEEDED")

    booking["status"] = "CONFIRMED"
    touch(booking)
    cascade.bump_venue(venue)
    return ok(serial.booking(booking))


@bp.post("/event-bookings/<booking_id>/release")
def release_booking(booking_id):
    v.auth(("BookingManager",))
    payload = v.body()
    reason = v.req_str(payload, "reason", 1, 500)
    booking = get_booking(booking_id)

    # Ladder 9: from-state legality.
    if booking["status"] not in RELEASABLE_STATES:
        raise ApiError("ERR_INVALID_BOOKING_STATE")
    if booking["status"] == "CONFIRMED":
        for order in db.orders.values():
            if order["to_booking_id"] == booking["id"] and order["status"] == "SIGNED_OFF":
                raise ApiError("ERR_INVALID_BOOKING_STATE",
                               "A signed-off turnaround already converted the building "
                               "for this booking.")

    cascade.release_booking(booking, reason)
    venue = db.venues.get(booking["venue_id"])
    if venue is not None:
        cascade.bump_venue(venue)
    return ok(serial.booking(booking))


@bp.post("/venues/<venue_id>/hold-expiry-sweep")
def hold_expiry_sweep(venue_id):
    v.auth(("BookingManager",))
    venue = get_venue(venue_id)
    now = now_logical()
    due = [b for b in db.bookings.values()
           if b["venue_id"] == venue["id"]
           and b["status"] in ("HELD", "CHALLENGED")
           and b["hold_expires_at"] is not None
           and b["hold_expires_at"] <= now]
    # Pinned processing order: hold_expires_at ascending, created_at as tie-break.
    due.sort(key=lambda b: (b["hold_expires_at"], b["created_at"], b["_seq"]))
    released = []
    for booking in due:
        cascade.release_booking(booking, "HOLD_EXPIRY_SWEEP")
        released.append(booking["id"])
    if released:
        cascade.bump_venue(venue)
    return ok({
        "swept_count": len(released),
        "released_booking_ids": released,
        "venue_version": int(venue["version"]),
    })
