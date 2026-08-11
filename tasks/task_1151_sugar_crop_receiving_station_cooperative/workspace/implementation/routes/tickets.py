from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request as _req

import db
import response
import serializers
import services.cascade as cascade
from errors import raise_err
from middleware import check_member_ownership, require_roles
from routes._common import as_decimal, body, pagination_args, req_field, sorted_page
from services.calc import (
    D,
    REJECT_TRASH_PCT,
    adjusted_net_tons,
    payment_factor_final,
    provisional_value_cents,
    waitlist_promotion_scan,
)

bp = Blueprint("tickets", __name__)


def _weigh_window_ok(booking):
    now = db.now()
    return (booking["slot_start"] - timedelta(seconds=1800)) <= now <= (booking["slot_end"] + timedelta(seconds=3600))


@bp.post("/api/tickets")
def create_ticket():
    require_roles(["STATION_OPERATOR"])
    data = body()
    booking_id = req_field(data, "booking_id")
    b = db.bookings.get(booking_id)
    if not b:
        raise_err("ERR_NOT_FOUND", "Booking not found")
    if b["status"] not in ("CONFIRMED", "IN_USE"):
        raise_err("ERR_BOOKING_NOT_CONFIRMED", "Booking must be CONFIRMED or IN_USE")
    member = db.members.get(b["member_id"])
    if member and member["status"] != "ACTIVE":
        raise_err("ERR_MEMBER_SUSPENDED", "Member is SUSPENDED")
    t = db.stamp_new({
        "booking_id": booking_id,
        "member_id": b["member_id"],
        "station_id": b["station_id"],
        "gross_weight_lbs": None,
        "tare_weight_lbs": None,
        "net_weight_lbs": None,
        "status": "CREATED",
        "provisional_trash_pct": None,
        "provisional_sugar_pct": None,
        "provisional_factor": None,
        "provisional_adjusted_net_tons": None,
        "provisional_value_cents": None,
        "final_trash_pct": None,
        "final_sugar_pct": None,
        "final_factor": None,
        "adjusted_net_tons_final": None,
        "adjusted_net_lbs_final": None,
    })
    db.tickets[t["id"]] = t
    return response.success(serializers.ticket(t), 201)


@bp.get("/api/tickets/<ticket_id>")
def get_ticket(ticket_id):
    user_id, role = require_roles(["COOP_ADMIN", "STATION_OPERATOR", "QUALITY_TECH", "SCHEDULER", "POOL_ACCOUNTANT", "MEMBER"])
    t = db.tickets.get(ticket_id)
    if not t:
        raise_err("ERR_NOT_FOUND", "Ticket not found")
    check_member_ownership(user_id, role, t["member_id"])
    return response.success(serializers.ticket(t), 200)


@bp.get("/api/tickets")
def list_tickets():
    user_id, role = require_roles(["COOP_ADMIN", "STATION_OPERATOR", "QUALITY_TECH", "SCHEDULER", "POOL_ACCOUNTANT", "MEMBER"])
    booking_id = _req.args.get("booking_id")
    member_id = _req.args.get("member_id")
    station_id = _req.args.get("station_id")
    status = _req.args.get("status")
    limit, offset = pagination_args()
    if role == "MEMBER":
        member_id = user_id
    items = list(db.tickets.values())
    if booking_id is not None:
        items = [t for t in items if t["booking_id"] == booking_id]
    if member_id is not None:
        items = [t for t in items if t["member_id"] == member_id]
    if station_id is not None:
        items = [t for t in items if t["station_id"] == station_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, total = sorted_page(items, limit, offset)
    return response.success_list([serializers.ticket(t) for t in page], total, limit, offset, 200)


@bp.post("/api/tickets/<ticket_id>/weigh")
def weigh_ticket(ticket_id):
    require_roles(["STATION_OPERATOR"])
    data = body()
    gross = as_decimal(req_field(data, "gross_weight_lbs"), "gross_weight_lbs")
    tare = as_decimal(req_field(data, "tare_weight_lbs"), "tare_weight_lbs")
    t = db.tickets.get(ticket_id)
    if not t:
        raise_err("ERR_NOT_FOUND", "Ticket not found")
    if t["status"] not in ("CREATED", "REWEIGHING"):
        raise_err("ERR_INVALID_STATE", "Ticket must be CREATED or REWEIGHING to weigh")
    b = db.bookings.get(t["booking_id"])
    if tare <= 0 or gross <= tare:
        raise_err("ERR_INVALID_WEIGHTS", "tare_weight_lbs must be > 0 and gross_weight_lbs > tare_weight_lbs")
    if not _weigh_window_ok(b):
        raise_err("ERR_WEIGH_WINDOW_CLOSED", "Logical clock outside the booking weigh window")
    t["gross_weight_lbs"] = gross
    t["tare_weight_lbs"] = tare
    t["net_weight_lbs"] = gross - tare
    t["status"] = "WEIGHED"
    db.touch(t)
    if b["status"] == "CONFIRMED":
        b["status"] = "IN_USE"
        db.touch(b)
    return response.success(serializers.ticket(t), 200)


@bp.post("/api/tickets/<ticket_id>/reweigh")
def reweigh_ticket(ticket_id):
    require_roles(["STATION_OPERATOR"])
    t = db.tickets.get(ticket_id)
    if not t:
        raise_err("ERR_NOT_FOUND", "Ticket not found")
    if t["status"] != "WEIGHED":
        raise_err("ERR_INVALID_STATE", "Ticket must be WEIGHED to reweigh")
    b = db.bookings.get(t["booking_id"])
    if not _weigh_window_ok(b):
        raise_err("ERR_WEIGH_WINDOW_CLOSED", "Logical clock outside the booking weigh window")
    t["gross_weight_lbs"] = None
    t["tare_weight_lbs"] = None
    t["net_weight_lbs"] = None
    t["status"] = "REWEIGHING"
    db.touch(t)
    return response.success(serializers.ticket(t), 200)


@bp.post("/api/tickets/<ticket_id>/accept")
def accept_ticket(ticket_id):
    require_roles(["STATION_OPERATOR"])
    data = body()
    pile_id = req_field(data, "pile_id")
    t = db.tickets.get(ticket_id)
    if not t:
        raise_err("ERR_NOT_FOUND", "Ticket not found")
    pile = db.piles.get(pile_id)
    if not pile:
        raise_err("ERR_NOT_FOUND", "Pile not found")
    if t["status"] != "SAMPLED":
        raise_err("ERR_INVALID_STATE", "Ticket must be SAMPLED to accept")

    # latest VERIFIED LAB_VERIFY sample by created_at
    verified_lab = [
        s for s in db.samples.values()
        if s["ticket_id"] == ticket_id and s["sample_type"] == "LAB_VERIFY" and s["status"] == "VERIFIED"
    ]
    if not verified_lab:
        raise_err("ERR_LAB_SAMPLE_REQUIRED", "At least one VERIFIED LAB_VERIFY sample is required")
    verified_lab.sort(key=lambda s: (s["created_at"], s["id"]))
    latest = verified_lab[-1]
    final_trash = D(latest["trash_pct"])
    final_sugar = D(latest["sugar_pct"])

    if final_trash > REJECT_TRASH_PCT:
        raise_err("ERR_TRASH_LIMIT_EXCEEDED", "final_trash_pct exceeds 20.00")
    if pile["fill_status"] != "FILLING":
        raise_err("ERR_PILE_NOT_FILLING", "Pile is not FILLING")
    if pile["station_id"] != t["station_id"]:
        raise_err("ERR_PILE_STATION_MISMATCH", "Pile station does not match ticket station")

    adjusted_tons = adjusted_net_tons(t["net_weight_lbs"], final_trash)
    adjusted_lbs = adjusted_tons * Decimal("2000")

    capacity_lbs = D(pile["capacity_tons"]) * Decimal("2000")
    if D(pile["stored_lbs"]) + adjusted_lbs > capacity_lbs:
        raise_err("ERR_PILE_CAPACITY_EXCEEDED", "Pile capacity would be exceeded")

    final_factor = payment_factor_final(final_sugar)

    t["final_trash_pct"] = final_trash
    t["final_sugar_pct"] = final_sugar
    t["final_factor"] = final_factor
    t["adjusted_net_tons_final"] = adjusted_tons
    t["adjusted_net_lbs_final"] = adjusted_lbs
    t["status"] = "ACCEPTED"
    db.touch(t)

    alloc = db.stamp_new({
        "ticket_id": t["id"],
        "pile_id": pile["id"],
        "member_id": t["member_id"],
        "allocated_lbs": adjusted_lbs,
        "remaining_lbs": adjusted_lbs,
        "status": "ACTIVE",
    })
    db.pile_allocations[alloc["id"]] = alloc

    pile["stored_lbs"] = D(pile["stored_lbs"]) + adjusted_lbs
    db.touch(pile)

    b = db.bookings.get(t["booking_id"])
    station = db.stations.get(t["station_id"])
    if b and b["status"] == "IN_USE":
        b["status"] = "COMPLETED"
        db.touch(b)
        if station:
            station["booked_tons"] = D(station["booked_tons"]) - D(b["estimated_tons"])
            db.touch(station)
    if station:
        cascade.recompute_station(station["id"])
        waitlist_promotion_scan(station)

    return response.success(serializers.ticket(t), 200)


@bp.post("/api/tickets/<ticket_id>/reject")
def reject_ticket(ticket_id):
    require_roles(["STATION_OPERATOR"])
    t = db.tickets.get(ticket_id)
    if not t:
        raise_err("ERR_NOT_FOUND", "Ticket not found")
    if t["status"] != "SAMPLED":
        raise_err("ERR_INVALID_STATE", "Ticket must be SAMPLED to reject")
    if not (t["provisional_trash_pct"] is not None and D(t["provisional_trash_pct"]) > REJECT_TRASH_PCT):
        raise_err("ERR_INVALID_STATE", "Ticket is within the trash limit")
    t["status"] = "REJECTED"
    db.touch(t)
    return response.success(serializers.ticket(t), 200)


@bp.post("/api/tickets/<ticket_id>/void")
def void_ticket(ticket_id):
    require_roles(["STATION_OPERATOR"])
    t = db.tickets.get(ticket_id)
    if not t:
        raise_err("ERR_NOT_FOUND", "Ticket not found")
    if t["status"] not in ("CREATED", "WEIGHED", "SAMPLED"):
        raise_err("ERR_INVALID_STATE", "Ticket cannot be voided from its current state")
    t["status"] = "VOIDED"
    db.touch(t)
    return response.success(serializers.ticket(t), 200)


@bp.post("/api/tickets/<ticket_id>/credit")
def credit_ticket(ticket_id):
    require_roles(["POOL_ACCOUNTANT"])
    t = db.tickets.get(ticket_id)
    if not t:
        raise_err("ERR_NOT_FOUND", "Ticket not found")
    if t["status"] != "ACCEPTED":
        raise_err("ERR_TICKET_NOT_CREDITABLE", "Ticket is not ACCEPTED")
    b = db.bookings.get(t["booking_id"])
    pool = cascade.get_campaign_pool(b["campaign_id"])
    if not pool or pool["status"] != "ACCRUING":
        raise_err("ERR_POOL_NOT_ACCRUING", "Pool is not ACCRUING")
    cap = int(pool["estimated_pool_value_cents"]) * Decimal("1.10")
    if Decimal(int(pool["accrued_provisional_cents"])) + Decimal(int(t["provisional_value_cents"])) > cap:
        raise_err("ERR_POOL_ACCRUAL_CAP_EXCEEDED", "Accrual cap would be exceeded")
    pool["accrued_provisional_cents"] = int(pool["accrued_provisional_cents"]) + int(t["provisional_value_cents"])
    db.touch(pool)
    t["status"] = "CREDITED"
    db.touch(t)
    return response.success(serializers.ticket(t), 200)
