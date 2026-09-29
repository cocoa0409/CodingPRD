"""Booking lifecycle, metering evidence and trip photography."""

from datetime import timedelta

from flask import Blueprint

import calc
import enums
import serializers as ser
import services as svc
import validation as v
from envelope import list_response, object_response
from errors import fail
from store import (clock_date, creation_order, db, new_record, parse_date,
                   parse_dt, touch)
from web import paged, route

bp = Blueprint("bookings", __name__)

_LIVE = ("REQUESTED", "OWNER_APPROVED", "CONFIRMED", "IN_TRIP", "RETURNED")

_CANCEL_FROM = {
    "Renter": ("REQUESTED", "OWNER_APPROVED", "CONFIRMED"),
    "Owner": ("CONFIRMED",),
    "PlatformAdmin": ("REQUESTED", "OWNER_APPROVED", "CONFIRMED"),
}


def _require_trip_status(booking, allowed):
    if booking["trip_status"] not in allowed:
        fail("ERR_BOOKING_STATE_INVALID",
             "Booking.trip_status %s does not permit this transition."
             % booking["trip_status"])


def _require_settlement_status(booking, allowed):
    if booking["settlement_status"] not in allowed:
        fail("ERR_SETTLEMENT_STATE_INVALID",
             "Booking.settlement_status %s does not permit this transition."
             % booking["settlement_status"])


def _readings(booking_id, reading_type=None):
    rows = [r for r in db.meter_readings.values() if r["booking_id"] == booking_id]
    if reading_type is not None:
        rows = [r for r in rows if r["reading_type"] == reading_type]
    return rows


def _photo_zones(booking_id, phase):
    return {p["zone"] for p in db.trip_photos.values()
            if p["booking_id"] == booking_id and p["phase"] == phase}


def _require_evidence(booking, reading_type, phase):
    if not _readings(booking["id"], reading_type):
        fail("ERR_METER_READINGS_INCOMPLETE",
             "A %s meter reading is required." % reading_type)
    if len(_photo_zones(booking["id"], phase)) < calc.MIN_TRIP_PHOTO_ZONES:
        fail("ERR_TRIP_PHOTOS_INCOMPLETE",
             "%s photos must cover at least %d distinct zones."
             % (phase, calc.MIN_TRIP_PHOTO_ZONES))


# ---------------------------------------------------------------- bookings -----
@route(bp, "/bookings", ["POST"], ("Renter",))
def create_booking(user_id, role):
    body = v.body()
    listing_id = v.get_str(body, "listing_id")
    renter_id = v.get_str(body, "renter_id")
    protection_plan_id = v.get_str(body, "protection_plan_id")
    cancellation_policy_id = v.get_str(body, "cancellation_policy_id")
    start_date = v.get_date(body, "start_date")
    end_date = v.get_date(body, "end_date")
    delivery_option = v.get_enum(body, "delivery_option", enums.DELIVERY_OPTION)
    declared_miles = v.get_int(body, "declared_miles", 0)
    declared_generator_hours = v.get_tenth(body, "declared_generator_hours", 0)

    listing = svc.lookup("listings", listing_id)
    renter = svc.lookup("renters", renter_id)
    plan = svc.lookup("protection_plans", protection_plan_id)
    policy = svc.lookup("cancellation_policies", cancellation_policy_id)
    if renter_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "A booking may only be requested for the acting renter.")

    start = parse_date(start_date)
    end = parse_date(end_date)
    nights = (end - start).days

    if listing["listing_status"] != "LISTED":
        fail("ERR_LISTING_NOT_BOOKABLE", "The listing is not LISTED.")

    age = calc.age_years(renter["date_of_birth"], start)
    if age < listing["min_renter_age"]:
        fail("ERR_RENTER_AGE_BELOW_MINIMUM",
             "The renter is below the listing's minimum age.")

    newest = calc.newest_driving_record(renter_id)
    if (newest is None or newest["result"] not in ("CLEAR", "MINOR")
            or parse_date(newest["expires_on"]) < end):
        fail("ERR_DRIVING_RECORD_INVALID",
             "A valid, unexpired driving-record check with result CLEAR or MINOR is required.")

    if calc.rolling_record_points(renter_id) > calc.MAX_RECORD_POINTS:
        fail("ERR_DRIVING_RECORD_POINTS_EXCEEDED",
             "The renter's rolling driving-record points exceed the limit.")

    trip_tier = calc.towing_tier(renter_id, end)
    if listing["requires_towing"]:
        if trip_tier == "NONE":
            fail("ERR_TOWING_EXPERIENCE_MISSING",
                 "The rig requires verified towing experience.")
        if (listing["gvwr_lbs"] > calc.TOWING_ADVANCED_GVWR_THRESHOLD_LBS
                and trip_tier != "ADVANCED"):
            fail("ERR_TOWING_TIER_INSUFFICIENT",
                 "This rig's weight requires ADVANCED towing verification.")

    if renter["renter_penalty_points"] >= calc.RENTER_BLOCK_POINT_THRESHOLD:
        fail("ERR_RENTER_BLOCKED", "The renter is blocked by penalty points.")

    svc.recompute_listing_derived(listing)
    if listing["insurance_status"] != "VERIFIED":
        fail("ERR_LISTING_INSURANCE_NOT_VERIFIED",
             "The listing's insurance is not VERIFIED.")

    for other in db.bookings.values():
        if other["listing_id"] != listing_id or other["trip_status"] not in _LIVE:
            continue
        other_start = parse_date(other["start_date"])
        other_end = parse_date(other["end_date"])
        if (start < other_end + timedelta(days=calc.TURNAROUND_BUFFER_NIGHTS)
                and end > other_start):
            fail("ERR_LISTING_DATES_UNAVAILABLE",
                 "The requested dates collide with an existing booking.")

    if start >= end or start < clock_date():
        fail("ERR_INVALID_DATE_RANGE",
             "start_date must precede end_date and must not fall in the past.")

    if listing["vehicle_class"] not in plan["eligible_vehicle_classes"]:
        fail("ERR_PLAN_CLASS_NOT_ELIGIBLE",
             "The protection plan does not cover this vehicle class.")

    if delivery_option == "CAMPGROUND_DROPOFF" and not listing["delivery_offered"]:
        fail("ERR_DELIVERY_NOT_OFFERED", "This listing does not offer delivery.")

    calc.recompute_renter_qualification(renter)
    snapshot = newest["violation_points"] if newest is not None else 0
    booking = new_record(
        listing_id=listing_id, renter_id=renter_id,
        protection_plan_id=protection_plan_id,
        cancellation_policy_id=cancellation_policy_id,
        start_date=start_date, end_date=end_date, delivery_option=delivery_option,
        declared_miles=declared_miles,
        declared_generator_hours=declared_generator_hours,
        nights=nights, trip_status="REQUESTED", settlement_status="NONE",
        renter_age_years_at_start=age, renter_record_points_snapshot=snapshot,
        towing_verified_tier=renter["towing_verified_tier"],
        base_subtotal_cents=0, premium_cents=0, delivery_fee_cents=0,
        loyalty_tier="NONE", loyalty_discount_cents=0, service_fee_cents=0,
        estimated_overage_cents=0, quoted_total_cents=0, hold_amount_cents=0,
        final_overage_cents=0, trip_total_overage_cents=0, late_return_fee_cents=0,
        final_total_cents=0, balance_due_cents=0, refund_cents=0, info_round_count=0,
        cancel_reason=None, reversal_reason=None)
    booking["base_subtotal_cents"] = calc.booking_nightly_subtotal(listing, start, nights)
    booking["premium_cents"] = calc.protection_premium(
        listing, plan, nights, booking["base_subtotal_cents"],
        booking["towing_verified_tier"])
    calc.quote_total(booking, listing)
    db.bookings[booking["id"]] = booking
    return object_response(ser.dump("booking", booking), 201)


@route(bp, "/bookings/<booking_id>", ["GET"],
       ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def get_booking(user_id, role, booking_id):
    booking = svc.lookup("bookings", booking_id)
    return object_response(ser.dump("booking", booking))


@route(bp, "/bookings", ["GET"], ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def list_bookings(user_id, role):
    limit, offset = v.pagination()
    listing_id = v.query_str("listing_id")
    renter_id = v.query_str("renter_id")
    protection_plan_id = v.query_str("protection_plan_id")
    cancellation_policy_id = v.query_str("cancellation_policy_id")
    trip_status = v.query_enum("trip_status", enums.TRIP_STATUS)
    settlement_status = v.query_enum("settlement_status", enums.SETTLEMENT_STATUS)
    rows = creation_order(list(db.bookings.values()))
    if listing_id is not None:
        rows = [r for r in rows if r["listing_id"] == listing_id]
    if renter_id is not None:
        rows = [r for r in rows if r["renter_id"] == renter_id]
    if protection_plan_id is not None:
        rows = [r for r in rows if r["protection_plan_id"] == protection_plan_id]
    if cancellation_policy_id is not None:
        rows = [r for r in rows if r["cancellation_policy_id"] == cancellation_policy_id]
    if trip_status is not None:
        rows = [r for r in rows if r["trip_status"] == trip_status]
    if settlement_status is not None:
        rows = [r for r in rows if r["settlement_status"] == settlement_status]
    return list_response(ser.dump_all("booking", paged(rows, limit, offset)),
                         limit, offset, len(rows))


@route(bp, "/bookings/<booking_id>/approve", ["POST"], ("Owner",))
def approve_booking(user_id, role, booking_id):
    v.body()
    booking = svc.lookup("bookings", booking_id)
    svc.require_booking_access(role, user_id, booking)
    _require_trip_status(booking, ("REQUESTED",))
    listing = svc.listing_of(booking)
    if listing["listing_status"] != "LISTED":
        fail("ERR_LISTING_NOT_BOOKABLE", "The listing is not LISTED.")
    owner = svc.owner_of_listing(listing)
    if owner["status"] != "ACTIVE":
        fail("ERR_OWNER_SUSPENDED", "A suspended owner may not approve bookings.")
    booking["trip_status"] = "OWNER_APPROVED"
    touch(booking)
    return object_response(ser.dump("booking", booking))


@route(bp, "/bookings/<booking_id>/confirm", ["POST"], ("Renter",))
def confirm_booking(user_id, role, booking_id):
    v.body()
    booking = svc.lookup("bookings", booking_id)
    svc.require_booking_access(role, user_id, booking)
    _require_trip_status(booking, ("OWNER_APPROVED",))
    listing = svc.listing_of(booking)
    if listing["listing_status"] != "LISTED":
        fail("ERR_LISTING_NOT_BOOKABLE", "The listing is not LISTED.")
    svc.recompute_quote_full(booking)
    renter = db.renters[booking["renter_id"]]
    if renter["wallet_credit_cents"] < booking["quoted_total_cents"]:
        fail("ERR_INSUFFICIENT_RENTER_FUNDS",
             "The renter's wallet does not cover the quoted total.")
    booking["hold_amount_cents"] = booking["quoted_total_cents"]
    renter["wallet_credit_cents"] -= booking["hold_amount_cents"]
    touch(renter)
    booking["trip_status"] = "CONFIRMED"
    booking["settlement_status"] = "HELD"
    touch(booking)
    return object_response(ser.dump("booking", booking))


@route(bp, "/bookings/<booking_id>/start", ["POST"], ("Owner",))
def start_booking(user_id, role, booking_id):
    v.body()
    booking = svc.lookup("bookings", booking_id)
    svc.require_booking_access(role, user_id, booking)
    _require_trip_status(booking, ("CONFIRMED",))
    scheduled = [a for a in db.delivery_assignments.values()
                 if a["booking_id"] == booking["id"] and a["status"] == "SCHEDULED"]
    if booking["delivery_option"] == "CAMPGROUND_DROPOFF" and not scheduled:
        fail("ERR_ASSIGNMENT_STATE_INVALID",
             "A SCHEDULED delivery assignment is required before handover.")
    _require_evidence(booking, "PRE_TRIP", "PRE_TRIP")

    booking["trip_status"] = "IN_TRIP"
    touch(booking)
    for assignment in creation_order(scheduled):
        assignment["status"] = "COMPLETED"
        touch(assignment)
        campground = db.campgrounds.get(assignment["campground_id"])
        if campground is not None:
            svc.sync_campground_count(campground, -1)
            svc.promote_waitlist(campground, assignment["dropoff_date"])
    return object_response(ser.dump("booking", booking))


@route(bp, "/bookings/<booking_id>/return", ["POST"], ("Owner", "Renter"))
def return_booking(user_id, role, booking_id):
    v.body()
    booking = svc.lookup("bookings", booking_id)
    svc.require_booking_access(role, user_id, booking)
    _require_trip_status(booking, ("IN_TRIP",))
    _require_evidence(booking, "POST_TRIP", "POST_TRIP")

    listing = svc.listing_of(booking)
    readings = calc.sorted_readings(booking["id"])
    booking["final_overage_cents"] = calc.segment_wise_overage(listing, readings)
    booking["trip_total_overage_cents"] = calc.trip_total_overage(listing, booking, readings)
    booking["late_return_fee_cents"] = calc.late_return_fee(listing, booking)
    calc.final_trip_total(booking)
    booking["trip_status"] = "RETURNED"
    booking["settlement_status"] = "RECONCILING"
    touch(booking)
    return object_response(ser.dump("booking", booking))


@route(bp, "/bookings/<booking_id>/settle", ["POST"], ("PlatformAdmin",))
def settle_booking(user_id, role, booking_id):
    v.body()
    booking = svc.lookup("bookings", booking_id)
    _require_trip_status(booking, ("RETURNED",))
    _require_settlement_status(booking, ("RECONCILING",))
    if svc.open_claims(booking["id"]):
        fail("ERR_CLAIM_STATE_INVALID", "An open damage claim blocks settlement.")
    renter = db.renters[booking["renter_id"]]
    if (booking["balance_due_cents"] > 0
            and renter["wallet_credit_cents"] < booking["balance_due_cents"]):
        fail("ERR_INSUFFICIENT_RENTER_FUNDS",
             "The renter's wallet does not cover the outstanding balance.")
    svc.settle_booking(booking)
    return object_response(ser.dump("booking", booking))


@route(bp, "/bookings/<booking_id>/settlement/reverse", ["POST"], ("PlatformAdmin",))
def reverse_settlement(user_id, role, booking_id):
    body = v.body()
    reversal_reason = v.get_str(body, "reversal_reason", min_len=1)
    booking = svc.lookup("bookings", booking_id)
    _require_settlement_status(booking, ("SETTLED",))
    svc.reverse_settlement(booking, reversal_reason)
    return object_response(ser.dump("booking", booking))


@route(bp, "/bookings/<booking_id>/cancel", ["POST"], ("Owner", "Renter", "PlatformAdmin"))
def cancel_booking(user_id, role, booking_id):
    body = v.body()
    cancel_reason = v.get_str(body, "cancel_reason", min_len=1)
    booking = svc.lookup("bookings", booking_id)
    svc.require_booking_access(role, user_id, booking)
    _require_trip_status(booking, _CANCEL_FROM[role])
    svc.cancel_booking(booking, role, cancel_reason)
    return object_response(ser.dump("booking", booking))


# ----------------------------------------------------------- meter readings ----
@route(bp, "/meter-readings", ["POST"], ("Owner", "Renter"))
def create_reading(user_id, role):
    body = v.body()
    booking_id = v.get_str(body, "booking_id")
    reading_type = v.get_enum(body, "reading_type", enums.READING_TYPE)
    odometer_miles = v.get_int(body, "odometer_miles", 0)
    generator_hours = v.get_tenth(body, "generator_hours", 0)
    recorded_at = v.get_datetime(body, "recorded_at")
    booking = svc.lookup("bookings", booking_id)
    svc.require_booking_access(role, user_id, booking)

    stamp = parse_dt(recorded_at)
    existing = calc.sorted_readings(booking_id)
    if any(row["_recorded_at"] == stamp for row in existing):
        fail("ERR_METER_READING_REGRESSION",
             "Another reading already carries that recorded_at.")
    preceding = None
    for row in existing:
        if row["_recorded_at"] < stamp:
            preceding = row
    if preceding is not None and (
            odometer_miles < preceding["odometer_miles"]
            or generator_hours < calc.dec(preceding["generator_hours"])):
        fail("ERR_METER_READING_REGRESSION",
             "Odometer and generator hours must be non-decreasing.")

    reading = new_record(with_version=False, booking_id=booking_id,
                         reading_type=reading_type, odometer_miles=odometer_miles,
                         generator_hours=generator_hours, recorded_at=recorded_at,
                         _recorded_at=stamp)
    db.meter_readings[reading["id"]] = reading
    return object_response(ser.dump("meter_reading", reading), 201)


@route(bp, "/meter-readings/<reading_id>", ["GET"],
       ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def get_reading(user_id, role, reading_id):
    reading = svc.lookup("meter_readings", reading_id)
    return object_response(ser.dump("meter_reading", reading))


@route(bp, "/meter-readings", ["GET"],
       ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def list_readings(user_id, role):
    limit, offset = v.pagination()
    booking_id = v.query_str("booking_id")
    reading_type = v.query_enum("reading_type", enums.READING_TYPE)
    rows = creation_order(list(db.meter_readings.values()))
    if booking_id is not None:
        rows = [r for r in rows if r["booking_id"] == booking_id]
    if reading_type is not None:
        rows = [r for r in rows if r["reading_type"] == reading_type]
    return list_response(ser.dump_all("meter_reading", paged(rows, limit, offset)),
                         limit, offset, len(rows))


# -------------------------------------------------------------- trip photos ----
@route(bp, "/trip-photos", ["POST"], ("Owner", "Renter"))
def create_photo(user_id, role):
    body = v.body()
    booking_id = v.get_str(body, "booking_id")
    phase = v.get_enum(body, "phase", enums.PHASE)
    zone = v.get_enum(body, "zone", enums.ZONE)
    damage_flagged = v.get_bool(body, "damage_flagged", required=False, default=False)
    image_ref = v.get_str(body, "image_ref", min_len=1, max_len=200)
    booking = svc.lookup("bookings", booking_id)
    svc.require_booking_access(role, user_id, booking)
    photo = new_record(with_version=False, booking_id=booking_id, phase=phase,
                       zone=zone, damage_flagged=damage_flagged, image_ref=image_ref)
    db.trip_photos[photo["id"]] = photo
    return object_response(ser.dump("trip_photo", photo), 201)


@route(bp, "/trip-photos/<photo_id>", ["GET"],
       ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def get_photo(user_id, role, photo_id):
    photo = svc.lookup("trip_photos", photo_id)
    return object_response(ser.dump("trip_photo", photo))


@route(bp, "/trip-photos", ["GET"],
       ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def list_photos(user_id, role):
    limit, offset = v.pagination()
    booking_id = v.query_str("booking_id")
    phase = v.query_enum("phase", enums.PHASE)
    zone = v.query_enum("zone", enums.ZONE)
    rows = creation_order(list(db.trip_photos.values()))
    if booking_id is not None:
        rows = [r for r in rows if r["booking_id"] == booking_id]
    if phase is not None:
        rows = [r for r in rows if r["phase"] == phase]
    if zone is not None:
        rows = [r for r in rows if r["zone"] == zone]
    return list_response(ser.dump_all("trip_photo", paged(rows, limit, offset)),
                         limit, offset, len(rows))
