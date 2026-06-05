"""Booking routes: create, read, list, reschedule, cancel, complete,
request-reclean, schedule-reclean.
"""
from datetime import timedelta

from flask import Blueprint, request

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     parse_pagination, paginate, ownership_customer)
from response import success, list_success
from constants import ADDON_CODES, SUPPLIES, RECLEAN_WINDOW_HOURS
from clock import clock
from util import parse_iso
from services import calc, collisions, ledger
from services import booking_ops

bp = Blueprint("bookings", __name__)


def _validate_add_ons(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise err("ERR_INVALID_REQUEST", "add_ons must be a list")
    for a in value:
        if a not in ADDON_CODES:
            raise err("ERR_INVALID_REQUEST", "invalid add-on: %s" % a)
    return list(value)


def _validate_supplies(value):
    if value is None:
        return "CUSTOMER"
    if value not in SUPPLIES:
        raise err("ERR_INVALID_REQUEST", "invalid supplies_provided_by")
    return value


@bp.route("/cleaning/bookings", methods=["POST"])
def create_booking():
    principal = authenticate()
    authorize(principal, {"Customer"})
    body = get_json_body()
    require_fields(body, ["customer_id", "address_id", "pricing_plan_id",
                          "scheduled_start"])
    # Existence resolved left-to-right: customer, address, pricing_plan,
    # then optional cleaner_id.
    customer = require_resource(db.customers, body["customer_id"], "customer")
    address = require_resource(db.addresses, body["address_id"], "address")
    plan = require_resource(db.pricing_plans, body["pricing_plan_id"], "pricing_plan")
    pinned_cleaner_id = body.get("cleaner_id")
    if pinned_cleaner_id is not None:
        require_resource(db.cleaners, pinned_cleaner_id, "cleaner")

    ownership_customer(principal, customer["id"])

    # Business checks (after structural/state gates). Address-archived
    # (priority 10) precedes cleaner-availability/clearance and collisions.
    if address.get("archived"):
        raise err("ERR_ADDRESS_ARCHIVED", "address is archived")

    add_ons = _validate_add_ons(body.get("add_ons"))
    supplies = _validate_supplies(body.get("supplies_provided_by"))
    scheduled_start = parse_iso(body["scheduled_start"])

    # Cleaner clearance / availability (priorities 6 / 11) then collisions
    # (priorities 12, 13) inside create_booking_record.
    cleaner = booking_ops.resolve_cleaner_for_booking(
        customer["id"], address["postal_code"], pinned_cleaner_id)

    booking = booking_ops.create_booking_record(
        customer=customer, address=address, plan=plan,
        scheduled_start=scheduled_start, add_ons=add_ons,
        supplies_provided_by=supplies, cleaner_id=cleaner["id"])
    return success(S.booking(booking), status=201)


@bp.route("/cleaning/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    principal = authenticate()
    authorize(principal, {"Customer", "Cleaner", "PlatformAdmin"})
    rec = require_resource(db.bookings, bid, "booking")
    if principal.role == "Customer" and principal.user_id != rec["customer_id"]:
        raise err("ERR_FORBIDDEN_OWNERSHIP", "customer does not own this booking")
    if principal.role == "Cleaner" and principal.user_id != rec.get("cleaner_id"):
        raise err("ERR_FORBIDDEN_OWNERSHIP", "cleaner is not assigned to this booking")
    return success(S.booking(rec), status=200)


@bp.route("/cleaning/bookings", methods=["GET"])
def list_bookings():
    principal = authenticate()
    authorize(principal, {"Customer", "Cleaner", "PlatformAdmin"})
    limit, offset = parse_pagination()
    records = list(db.bookings.values())
    for key in ("customer_id", "address_id", "pricing_plan_id", "cleaner_id",
                "series_id", "reclean_of_booking_id", "status"):
        val = request.args.get(key)
        if val is not None:
            records = [r for r in records if r.get(key) == val]
    if principal.role == "Customer":
        records = [r for r in records if r["customer_id"] == principal.user_id]
    elif principal.role == "Cleaner":
        records = [r for r in records if r.get("cleaner_id") == principal.user_id]
    page, total = paginate(records, limit, offset)
    return list_success([S.booking(r) for r in page], limit, offset, total)


@bp.route("/cleaning/bookings/<bid>/reschedule", methods=["POST"])
def reschedule_booking(bid):
    principal = authenticate()
    authorize(principal, {"Customer"})
    booking = require_resource(db.bookings, bid, "booking")
    ownership_customer(principal, booking["customer_id"])
    if booking["status"] not in ("SCHEDULED", "RESCHEDULED"):
        raise err("ERR_INVALID_STATE", "booking is not reschedulable")
    body = get_json_body()
    require_fields(body, ["scheduled_start"])

    # Pinned cleaner must still serve the address postal code.
    address = db.addresses.get(booking["address_id"])
    cleaner_id = booking.get("cleaner_id")
    if cleaner_id is not None:
        cleaner = db.cleaners.get(cleaner_id)
        if cleaner is not None and address is not None:
            if address["postal_code"] not in (cleaner.get("service_postal_codes") or []):
                raise err("ERR_NO_CLEANER_AVAILABLE",
                          "assigned cleaner no longer serves the area")

    new_add_ons = _validate_add_ons(body["add_ons"]) if "add_ons" in body and body["add_ons"] is not None else booking["add_ons"]
    new_supplies = _validate_supplies(body["supplies_provided_by"]) if body.get("supplies_provided_by") is not None else booking["supplies_provided_by"]
    new_start = parse_iso(body["scheduled_start"])
    new_end = calc.visit_window(booking["home_size"], new_start)

    # Collision checks against the NEW interval, excluding this booking.
    collisions.check_cleaner_double_booked(cleaner_id, new_start, new_end, exclude_booking_id=booking["id"])
    collisions.check_address_double_booked(booking["address_id"], new_start, new_end, exclude_booking_id=booking["id"])

    # Window fee under the RESCHEDULE branch against current scheduled_start.
    fee = calc.reschedule_or_cancel_fee(
        "RESCHEDULE", booking["quoted_price_cents"],
        booking["scheduled_start"], clock.now())
    booking["change_fee_cents"] = fee
    customer = db.customers.get(booking["customer_id"])
    if fee > 0:
        ledger.change_fee(customer, fee, booking["id"])

    # Apply the move and re-pin price if add-ons/supplies changed.
    addons_changed = new_add_ons != booking["add_ons"]
    supplies_changed = new_supplies != booking["supplies_provided_by"]
    booking["scheduled_start"] = new_start
    booking["scheduled_end"] = new_end
    booking["add_ons"] = new_add_ons
    booking["supplies_provided_by"] = new_supplies
    if addons_changed or supplies_changed:
        plan = db.pricing_plans.get(booking["pricing_plan_id"])
        booking["quoted_price_cents"] = calc.price_quote(
            is_reclean=booking.get("is_reclean", False), plan=plan,
            home_size=booking["home_size"], add_ons=new_add_ons,
            supplies_provided_by=new_supplies,
            lifetime_booking_count=customer.get("lifetime_booking_count", 0))

    booking["status"] = "RESCHEDULED"
    db.touch(booking)
    return success(S.booking(booking), status=200)


@bp.route("/cleaning/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    principal = authenticate()
    authorize(principal, {"Customer"})
    booking = require_resource(db.bookings, bid, "booking")
    ownership_customer(principal, booking["customer_id"])
    if booking["status"] not in ("SCHEDULED", "RESCHEDULED"):
        raise err("ERR_INVALID_STATE", "booking is not cancellable")
    customer = db.customers.get(booking["customer_id"])
    booking_ops.settle_cancellation(booking, customer)
    booking["status"] = "CANCELLED"
    db.touch(booking)
    return success(S.booking(booking), status=200)


@bp.route("/cleaning/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    principal = authenticate()
    authorize(principal, {"Cleaner"})
    booking = require_resource(db.bookings, bid, "booking")
    # Ownership: acting cleaner must be the assigned cleaner.
    if principal.user_id != booking.get("cleaner_id"):
        raise err("ERR_FORBIDDEN_OWNERSHIP", "cleaner is not assigned to this booking")
    if booking["status"] not in ("SCHEDULED", "RESCHEDULED"):
        raise err("ERR_INVALID_STATE", "booking is not completable")
    # current clock must be at or after scheduled_start.
    if clock.now() < booking["scheduled_start"]:
        raise err("ERR_INVALID_STATE", "cannot complete before scheduled_start")

    body = get_json_body()
    rating = body.get("rating")
    if rating is not None:
        if isinstance(rating, bool) or not isinstance(rating, int) or rating < 1 or rating > 5:
            raise err("ERR_INVALID_REQUEST", "rating must be an integer 1..5")

    cleaner = db.cleaners.get(booking["cleaner_id"])

    # Cleaner payout.
    base_payout = calc.cleaner_payout_base(booking["quoted_price_cents"])
    payout = {
        "cleaner_id": booking["cleaner_id"],
        "booking_id": booking["id"],
        "base_payout_cents": base_payout,
        "tip_cents": 0,
        "total_cents": base_payout,
    }
    db.insert(db.cleaner_payouts, payout)

    # Loyalty + completion counters (skipped for recleans).
    if not booking.get("is_reclean"):
        customer = db.customers.get(booking["customer_id"])
        customer["lifetime_booking_count"] = customer.get("lifetime_booking_count", 0) + 1
        db.touch(customer)
        cleaner["completed_job_count"] = cleaner.get("completed_job_count", 0) + 1

    # Rating folds in regardless of reclean status (rating is about the visit).
    if rating is not None:
        cleaner["rating_sum"] = cleaner.get("rating_sum", 0) + rating
        cleaner["rating_count"] = cleaner.get("rating_count", 0) + 1

    if rating is not None or not booking.get("is_reclean"):
        db.touch(cleaner)

    booking["status"] = "COMPLETED"
    booking["_completed_at"] = clock.now()
    db.touch(booking)
    return success(S.booking(booking), status=200)


@bp.route("/cleaning/bookings/<bid>/request-reclean", methods=["POST"])
def request_reclean(bid):
    principal = authenticate()
    authorize(principal, {"Customer"})
    booking = require_resource(db.bookings, bid, "booking")
    ownership_customer(principal, booking["customer_id"])
    # State gate: must be COMPLETED.
    if booking["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "booking is not COMPLETED")
    # Reclean eligibility (priority 7): not itself a reclean, and no existing
    # open reclean of this original.
    if booking.get("is_reclean"):
        raise err("ERR_RECLEAN_NOT_ELIGIBLE", "a reclean cannot itself be recleaned")
    for b in db.bookings.values():
        if b.get("reclean_of_booking_id") == booking["id"]:
            raise err("ERR_RECLEAN_NOT_ELIGIBLE", "an open reclean already exists")
    # Reclean window (priority 8): within RECLEAN_WINDOW_HOURS of completion.
    completed_at = booking.get("_completed_at")
    if completed_at is not None:
        deadline = completed_at + timedelta(hours=RECLEAN_WINDOW_HOURS)
        if clock.now() > deadline:
            raise err("ERR_RECLEAN_WINDOW_CLOSED", "reclean window has closed")
    booking["status"] = "RECLEAN_REQUESTED"
    db.touch(booking)
    return success(S.booking(booking), status=200)


@bp.route("/cleaning/bookings/<bid>/schedule-reclean", methods=["POST"])
def schedule_reclean(bid):
    principal = authenticate()
    authorize(principal, {"PlatformAdmin"})
    booking = require_resource(db.bookings, bid, "booking")
    if booking["status"] != "RECLEAN_REQUESTED":
        raise err("ERR_INVALID_STATE", "booking is not RECLEAN_REQUESTED")
    body = get_json_body()
    require_fields(body, ["scheduled_start"])
    scheduled_start = parse_iso(body["scheduled_start"])

    customer = db.customers.get(booking["customer_id"])
    address = db.addresses.get(booking["address_id"])
    plan = db.pricing_plans.get(booking["pricing_plan_id"])
    original_cleaner_id = booking.get("cleaner_id")

    # Spawn the reclean booking: is_reclean=true, quoted 0, cleaner copied
    # from the original. No collision checks block the guarantee reclean.
    reclean = booking_ops.create_booking_record(
        customer=customer, address=address, plan=plan,
        scheduled_start=scheduled_start, add_ons=booking.get("add_ons", []),
        supplies_provided_by=booking.get("supplies_provided_by", "CUSTOMER"),
        cleaner_id=original_cleaner_id, is_reclean=True,
        reclean_of_booking_id=booking["id"], run_collisions=False)

    booking["status"] = "RECLEAN_SCHEDULED"
    db.touch(booking)
    # The schedule-reclean operation's created resource is the spawned booking
    # (§3.7: it "spawns a brand-new booking" carrying is_reclean / quoted 0 /
    # reclean_of_booking_id). Return that new booking.
    return success(S.booking(reclean), status=200)
