"""Guide, Trip, and TripBooking endpoints."""
from flask import Blueprint, request

import store
from errors import err
import core as c

bp = Blueprint("trips", __name__)

CERTS = {"SWIFTWATER", "ALPINE", "WILDERNESS_FIRST_AID"}
REQ_CERTS = {"NONE", "SWIFTWATER", "ALPINE", "WILDERNESS_FIRST_AID"}


# ------------------------------- Guides ------------------------------------
@bp.post("/coop/guides")
def create_guide():
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    body = c.get_body()
    full_name = c.require_str(body, "full_name")
    certs = body.get("certifications", [])
    if certs is None:
        certs = []
    if not isinstance(certs, list) or any(x not in CERTS for x in certs):
        raise err("ERR_VALIDATION", "certifications must be a list of valid certification enums")
    guide = {"full_name": full_name, "certifications": certs, "status": "ACTIVE"}
    store.stamp_new(guide)
    store.guides[guide["id"]] = guide
    return c.ok(c.ser_guide(guide), 201)


@bp.get("/coop/guides/<gid>")
def get_guide(gid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Guide", "StoreStaff", "CoopAdmin"})
    c.require_owner_guide(ctx, gid)
    g = c.lookup("guides", gid)
    return c.ok(c.ser_guide(g))


# ------------------------------- Trips -------------------------------------
@bp.post("/coop/trips")
def create_trip():
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff", "CoopAdmin"})
    body = c.get_body()
    title = c.require_str(body, "title")
    start_raw = c.require_str(body, "start_time")
    end_raw = c.require_str(body, "end_time")
    capacity = c.require_int(body, "capacity")
    price_cents = c.require_int(body, "price_cents")
    req_cert = c.opt_enum(body, "required_certification", REQ_CERTS, "NONE")
    start = store._parse_instant(start_raw)
    end = store._parse_instant(end_raw)
    if not (end > start):
        raise err("ERR_INVALID_INTERVAL", "end_time must be after start_time")
    if capacity <= 0:
        raise err("ERR_INVALID_QUANTITY", "capacity must be > 0")
    trip = {
        "title": title,
        "guide_id": None,
        "start_time": start_raw,
        "end_time": end_raw,
        "capacity": capacity,
        "price_cents": price_cents,
        "required_certification": req_cert,
        "status": "DRAFT",
    }
    store.stamp_new(trip)
    store.trips[trip["id"]] = trip
    return c.ok(c.ser_trip(trip), 201)


@bp.get("/coop/trips")
def list_trips():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "Guide", "StoreStaff", "CoopAdmin"})
    items = list(store.trips.values())
    if ctx.role == "Guide":
        items = [t for t in items if t["guide_id"] == ctx.user_id]
    for key in ("guide_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t[key] == val]
    return c.paginate_and_serialize(items, c.ser_trip)


@bp.get("/coop/trips/<tid>")
def get_trip(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "Guide", "StoreStaff", "CoopAdmin"})
    t = c.lookup("trips", tid)
    if ctx.role == "Guide" and t["guide_id"] != ctx.user_id:
        raise err("ERR_UNAUTHORIZED", "guide may only read its assigned trips")
    return c.ok(c.ser_trip(t))


def _guide_schedule_conflict(guide_id, t_start, t_end, exclude_trip_id):
    for t in store.trips.values():
        if t["id"] == exclude_trip_id:
            continue
        if t["guide_id"] != guide_id:
            continue
        if t["status"] not in ("DRAFT", "OPEN", "DEPARTED"):
            continue
        g_start = store._parse_instant(t["start_time"])
        g_end = store._parse_instant(t["end_time"])
        if t_start <= g_end and g_start <= t_end:
            return True
    return False


@bp.post("/coop/trips/<tid>/assign-guide")
def assign_guide(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    body = c.get_body()
    guide_id = c.require_str(body, "guide_id")
    t = c.lookup("trips", tid)
    g = c.lookup("guides", guide_id)
    req = t["required_certification"]
    if req != "NONE" and req not in g["certifications"]:
        raise err("ERR_GUIDE_NOT_CERTIFIED", "guide lacks the required certification")
    t_start = store._parse_instant(t["start_time"])
    t_end = store._parse_instant(t["end_time"])
    if _guide_schedule_conflict(guide_id, t_start, t_end, tid):
        raise err("ERR_GUIDE_SCHEDULE_CONFLICT", "guide has a conflicting trip")
    t["guide_id"] = guide_id
    store.touch(t)
    return c.ok(c.ser_trip(t))


@bp.post("/coop/trips/<tid>/open")
def open_trip(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    t = c.lookup("trips", tid)
    if t["status"] != "DRAFT" or t["guide_id"] is None:
        raise err("ERR_INVALID_STATE", "trip must be DRAFT with an assigned guide")
    t["status"] = "OPEN"
    store.touch(t)
    return c.ok(c.ser_trip(t))


@bp.post("/coop/trips/<tid>/depart")
def depart_trip(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    t = c.lookup("trips", tid)
    if t["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "trip must be OPEN to depart")
    t["status"] = "DEPARTED"
    store.touch(t)
    return c.ok(c.ser_trip(t))


@bp.post("/coop/trips/<tid>/complete")
def complete_trip(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    t = c.lookup("trips", tid)
    if t["status"] != "DEPARTED":
        raise err("ERR_INVALID_STATE", "trip must be DEPARTED to complete")
    t["status"] = "COMPLETED"
    store.touch(t)
    for b in store.trip_bookings.values():
        if b["trip_id"] == tid and b["status"] == "CHECKED_IN":
            b["status"] = "COMPLETED"
            store.touch(b)
    return c.ok(c.ser_trip(t))


def _refund_booking(b):
    """Cancel a booking with points + wallet refund; bump member."""
    b["status"] = "CANCELLED"
    store.touch(b)
    member = store.members.get(b["member_id"])
    if b["points_redeemed"] > 0:
        c.append_ledger(b["member_id"], b["points_redeemed"], "BOOKING_REFUND", b["id"])
    if member is not None:
        member["wallet_credit_cents"] += (b["price_paid_cents"] - b["points_redeemed"])
        store.touch(member)


@bp.post("/coop/trips/<tid>/cancel")
def cancel_trip(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    t = c.lookup("trips", tid)
    if t["status"] not in ("DRAFT", "OPEN"):
        raise err("ERR_INVALID_STATE", "trip must be DRAFT or OPEN to cancel")
    t["status"] = "CANCELLED"
    store.touch(t)
    for b in store.trip_bookings.values():
        if b["trip_id"] == tid and b["status"] in ("CONFIRMED", "CHECKED_IN"):
            _refund_booking(b)
    return c.ok(c.ser_trip(t))


# --------------------------- Trip bookings ---------------------------------
@bp.post("/coop/trips/<tid>/bookings")
def create_booking(tid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member"})
    body = c.get_body()
    member_id = c.require_str(body, "member_id")
    points_redeemed = c.opt_int(body, "points_redeemed", 0)
    if points_redeemed < 0:
        raise err("ERR_VALIDATION", "points_redeemed must be >= 0")
    c.require_owner_member(ctx, member_id)
    t = c.lookup("trips", tid)
    member = c.lookup("members", member_id)
    if t["status"] != "OPEN":
        raise err("ERR_TRIP_NOT_OPEN", "trip is not OPEN")
    if member["membership_status"] != "ACTIVE":
        raise err("ERR_MEMBERSHIP_NOT_ACTIVE", "member is not ACTIVE")
    if c.seats_confirmed(tid) >= t["capacity"]:
        raise err("ERR_TRIP_FULL", "trip is full")
    if points_redeemed > c.loyalty_balance(member_id):
        raise err("ERR_INSUFFICIENT_POINTS", "insufficient loyalty points")
    booking = {
        "trip_id": tid,
        "member_id": member_id,
        "price_paid_cents": t["price_cents"],
        "points_redeemed": points_redeemed,
        "status": "CONFIRMED",
    }
    store.stamp_new(booking)
    store.trip_bookings[booking["id"]] = booking
    if points_redeemed > 0:
        c.append_ledger(member_id, -points_redeemed, "BOOKING_REDEEM", booking["id"])
    return c.ok(c.ser_booking(booking), 201)


@bp.get("/coop/trip-bookings")
def list_bookings():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    items = list(store.trip_bookings.values())
    if ctx.role == "Member":
        items = [b for b in items if b["member_id"] == ctx.user_id]
    for key in ("trip_id", "member_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [b for b in items if b[key] == val]
    return c.paginate_and_serialize(items, c.ser_booking)


@bp.get("/coop/trip-bookings/<bid>")
def get_booking(bid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    b = c.lookup("trip_bookings", bid)
    c.require_owner_member(ctx, b["member_id"])
    return c.ok(c.ser_booking(b))


@bp.post("/coop/trip-bookings/<bid>/check-in")
def check_in(bid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    b = c.lookup("trip_bookings", bid)
    if b["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "booking is not CONFIRMED")
    t = store.trips[b["trip_id"]]
    if t["status"] != "DEPARTED":
        raise err("ERR_INVALID_STATE", "trip is not DEPARTED")
    b["status"] = "CHECKED_IN"
    store.touch(b)
    return c.ok(c.ser_booking(b))


@bp.post("/coop/trip-bookings/<bid>/cancel")
def cancel_booking(bid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff"})
    b = c.lookup("trip_bookings", bid)
    c.require_owner_member(ctx, b["member_id"])
    if b["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "booking is not CONFIRMED")
    _refund_booking(b)
    return c.ok(c.ser_booking(b))
