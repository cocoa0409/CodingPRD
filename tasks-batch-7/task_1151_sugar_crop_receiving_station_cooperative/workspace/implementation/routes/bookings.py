from flask import Blueprint

import db
import response
import serializers
import services.cascade as cascade
from errors import raise_err
from middleware import check_member_ownership, require_roles
from routes._common import as_dt, as_decimal, body, pagination_args, req_field, sorted_page
from services.calc import D, waitlist_promotion_scan

bp = Blueprint("bookings", __name__)


def _check_slot_inside_window(campaign, slot_start, slot_end):
    if not (campaign["window_start"] <= slot_start and slot_end <= campaign["window_end"]):
        raise_err("ERR_SLOT_OUTSIDE_WINDOW", "Slot must lie fully inside the campaign window")


def _check_overlap(station_id, slot_start, slot_end, exclude_booking_id=None):
    for b in db.bookings.values():
        if b["station_id"] != station_id:
            continue
        if b["status"] != "CONFIRMED":
            continue
        if exclude_booking_id and b["id"] == exclude_booking_id:
            continue
        # half-open overlap: slot_start < other.slot_end AND other.slot_start < slot_end
        if slot_start < b["slot_end"] and b["slot_start"] < slot_end:
            raise_err("ERR_SLOT_OVERLAP", "Slot overlaps another CONFIRMED booking at this station")


@bp.post("/api/bookings")
def create_booking():
    user_id, role = require_roles(["MEMBER"])
    data = body()
    campaign_id = req_field(data, "campaign_id")
    station_id = req_field(data, "station_id")
    slot_start = as_dt(req_field(data, "slot_start"), "slot_start")
    slot_end = as_dt(req_field(data, "slot_end"), "slot_end")
    estimated_tons = as_decimal(req_field(data, "estimated_tons"), "estimated_tons")

    campaign = db.campaigns.get(campaign_id)
    station = db.stations.get(station_id)
    if not campaign:
        raise_err("ERR_NOT_FOUND", "Campaign not found")
    if not station:
        raise_err("ERR_NOT_FOUND", "Station not found")

    if estimated_tons <= 0:
        raise_err("ERR_INVALID_REQUEST", "estimated_tons must be > 0")
    if slot_end <= slot_start:
        raise_err("ERR_INVALID_REQUEST", "slot_end must be after slot_start")

    # member compliance (priority 7) before temporal checks? PRD: booking create requires member ACTIVE.
    # Validation order: state (campaign OPEN) is priority 5, member compliance 7, temporal 8.
    if campaign["status"] != "OPEN":
        raise_err("ERR_CAMPAIGN_NOT_OPEN", "Campaign is not OPEN")
    member = db.members.get(user_id)
    if not member:
        raise_err("ERR_NOT_FOUND", "Member not found")
    if member["status"] != "ACTIVE":
        raise_err("ERR_MEMBER_SUSPENDED", "Member is SUSPENDED")

    b = db.stamp_new({
        "member_id": user_id,
        "station_id": station_id,
        "campaign_id": campaign_id,
        "slot_start": slot_start,
        "slot_end": slot_end,
        "estimated_tons": estimated_tons,
        "status": "REQUESTED",
    })
    db.bookings[b["id"]] = b
    return response.success(serializers.booking(b), 201)


@bp.get("/api/bookings/<booking_id>")
def get_booking(booking_id):
    user_id, role = require_roles(["COOP_ADMIN", "STATION_OPERATOR", "SCHEDULER", "POOL_ACCOUNTANT", "MEMBER"])
    b = db.bookings.get(booking_id)
    if not b:
        raise_err("ERR_NOT_FOUND", "Booking not found")
    check_member_ownership(user_id, role, b["member_id"])
    return response.success(serializers.booking(b), 200)


@bp.get("/api/bookings")
def list_bookings():
    user_id, role = require_roles(["COOP_ADMIN", "STATION_OPERATOR", "SCHEDULER", "POOL_ACCOUNTANT", "MEMBER"])
    from flask import request as _req
    member_id = _req.args.get("member_id")
    station_id = _req.args.get("station_id")
    campaign_id = _req.args.get("campaign_id")
    status = _req.args.get("status")
    limit, offset = pagination_args()

    if role == "MEMBER":
        member_id = user_id  # members only see own bookings

    items = list(db.bookings.values())
    if member_id is not None:
        items = [b for b in items if b["member_id"] == member_id]
    if station_id is not None:
        items = [b for b in items if b["station_id"] == station_id]
    if campaign_id is not None:
        items = [b for b in items if b["campaign_id"] == campaign_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, total = sorted_page(items, limit, offset)
    return response.success_list([serializers.booking(b) for b in page], total, limit, offset, 200)


@bp.post("/api/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    require_roles(["SCHEDULER"])
    b = db.bookings.get(booking_id)
    if not b:
        raise_err("ERR_NOT_FOUND", "Booking not found")
    if b["status"] != "REQUESTED":
        raise_err("ERR_INVALID_STATE", "Booking is not REQUESTED")
    campaign = db.campaigns.get(b["campaign_id"])
    member = db.members.get(b["member_id"])
    station = db.stations.get(b["station_id"])
    if campaign["status"] != "OPEN":
        raise_err("ERR_CAMPAIGN_NOT_OPEN", "Campaign is not OPEN")
    if member["status"] != "ACTIVE":
        raise_err("ERR_MEMBER_SUSPENDED", "Member is SUSPENDED")
    _check_slot_inside_window(campaign, b["slot_start"], b["slot_end"])
    _check_overlap(b["station_id"], b["slot_start"], b["slot_end"], exclude_booking_id=b["id"])

    if D(station["booked_tons"]) + D(b["estimated_tons"]) <= D(station["booking_capacity_tons"]):
        b["status"] = "CONFIRMED"
        db.touch(b)
        station["booked_tons"] = D(station["booked_tons"]) + D(b["estimated_tons"])
        db.touch(station)
        cascade.recompute_station(station["id"])
    else:
        b["status"] = "WAITLISTED"
        db.touch(b)
    return response.success(serializers.booking(b), 200)


@bp.post("/api/bookings/<booking_id>/reschedule")
def reschedule_booking(booking_id):
    user_id, role = require_roles(["MEMBER"])
    data = body()
    slot_start = as_dt(req_field(data, "slot_start"), "slot_start")
    slot_end = as_dt(req_field(data, "slot_end"), "slot_end")
    b = db.bookings.get(booking_id)
    if not b:
        raise_err("ERR_NOT_FOUND", "Booking not found")
    check_member_ownership(user_id, role, b["member_id"])
    if b["status"] != "CONFIRMED":
        raise_err("ERR_INVALID_STATE", "Booking is not CONFIRMED")
    if slot_end <= slot_start:
        raise_err("ERR_INVALID_REQUEST", "slot_end must be after slot_start")
    campaign = db.campaigns.get(b["campaign_id"])
    station = db.stations.get(b["station_id"])
    _check_slot_inside_window(campaign, slot_start, slot_end)
    station["booked_tons"] = D(station["booked_tons"]) - D(b["estimated_tons"])
    db.touch(station)
    b["slot_start"] = slot_start
    b["slot_end"] = slot_end
    b["status"] = "REQUESTED"
    db.touch(b)
    cascade.recompute_station(station["id"])
    return response.success(serializers.booking(b), 200)


@bp.post("/api/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    user_id, role = require_roles(["MEMBER", "SCHEDULER"])
    b = db.bookings.get(booking_id)
    if not b:
        raise_err("ERR_NOT_FOUND", "Booking not found")
    if role == "MEMBER":
        check_member_ownership(user_id, role, b["member_id"])
    if b["status"] not in ("REQUESTED", "WAITLISTED", "CONFIRMED"):
        raise_err("ERR_INVALID_STATE", "Booking cannot be cancelled from its current state")
    was_confirmed = b["status"] == "CONFIRMED"
    station = db.stations.get(b["station_id"])
    b["status"] = "CANCELLED"
    db.touch(b)
    if was_confirmed and station:
        station["booked_tons"] = D(station["booked_tons"]) - D(b["estimated_tons"])
        db.touch(station)
        cascade.recompute_station(station["id"])
        waitlist_promotion_scan(station)
    return response.success(serializers.booking(b), 200)
