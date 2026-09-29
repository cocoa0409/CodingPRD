"""Rig listings, their documentation and the review lifecycle."""

from flask import Blueprint

import calc
import enums
import serializers as ser
import services as svc
import validation as v
from envelope import list_response, object_response
from errors import fail
from store import creation_order, db, new_record, parse_date, touch
from web import paged, route

bp = Blueprint("listings", __name__)


def _refreshed(listing):
    svc.recompute_listing_derived(listing)
    return listing


def _live_bookings(listing_id):
    return [b for b in db.bookings.values()
            if b["listing_id"] == listing_id
            and b["trip_status"] in enums.LIVE_TRIP_STATUS]


# ---------------------------------------------------------------- listings -----
@route(bp, "/listings", ["POST"], ("Owner",))
def create_listing(user_id, role):
    body = v.body()
    owner_id = v.get_str(body, "owner_id")
    nickname = v.get_str(body, "nickname", min_len=1, max_len=80)
    vehicle_class = v.get_enum(body, "vehicle_class", enums.VEHICLE_CLASS)
    gvwr_lbs = v.get_int(body, "gvwr_lbs", 1000, 30000)
    length_ft = v.get_int(body, "length_ft", 10, 45)
    base_nightly_rate_cents = v.get_int(body, "base_nightly_rate_cents", 1000)
    included_miles_per_night = v.get_int(body, "included_miles_per_night", 0)
    mileage_rate = v.get_int(body, "mileage_overage_rate_cents_per_mile", 0)
    included_generator_hours = v.get_tenth(body, "included_generator_hours_per_night", 0)
    generator_rate = v.get_int(body, "generator_overage_rate_cents_per_hour", 0)
    min_renter_age = v.get_int(body, "min_renter_age", 21, 30)
    delivery_offered = v.get_bool(body, "delivery_offered", required=False, default=False)
    delivery_base_fee_cents = v.get_int(body, "delivery_base_fee_cents", 0,
                                        required=False, default=0)
    delivery_per_mile_cents = v.get_int(body, "delivery_per_mile_cents", 0,
                                        required=False, default=0)
    svc.lookup("owners", owner_id)
    if owner_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "A listing may only be created for the acting owner.")
    listing = new_record(
        owner_id=owner_id, nickname=nickname, vehicle_class=vehicle_class,
        requires_towing=vehicle_class in enums.TOWING_CLASSES, gvwr_lbs=gvwr_lbs,
        length_ft=length_ft, base_nightly_rate_cents=base_nightly_rate_cents,
        included_miles_per_night=included_miles_per_night,
        mileage_overage_rate_cents_per_mile=mileage_rate,
        included_generator_hours_per_night=included_generator_hours,
        generator_overage_rate_cents_per_hour=generator_rate,
        min_renter_age=min_renter_age, delivery_offered=delivery_offered,
        delivery_base_fee_cents=delivery_base_fee_cents,
        delivery_per_mile_cents=delivery_per_mile_cents,
        listing_status="DRAFT", insurance_status="PENDING",
        inspection_photo_zone_count=0, completed_night_count=0,
        last_reconciled_at=None, suspend_reason=None, decision_note=None)
    db.listings[listing["id"]] = listing
    return object_response(ser.dump("listing", listing), 201)


@route(bp, "/listings/<listing_id>", ["GET"],
       ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def get_listing(user_id, role, listing_id):
    listing = svc.lookup("listings", listing_id)
    return object_response(ser.dump("listing", _refreshed(listing)))


@route(bp, "/listings", ["GET"], ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster"))
def list_listings(user_id, role):
    limit, offset = v.pagination()
    owner_id = v.query_str("owner_id")
    listing_status = v.query_enum("listing_status", enums.LISTING_STATUS)
    vehicle_class = v.query_enum("vehicle_class", enums.VEHICLE_CLASS)
    rows = creation_order(list(db.listings.values()))
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    if listing_status is not None:
        rows = [r for r in rows if r["listing_status"] == listing_status]
    if vehicle_class is not None:
        rows = [r for r in rows if r["vehicle_class"] == vehicle_class]
    page = [_refreshed(r) for r in paged(rows, limit, offset)]
    return list_response(ser.dump_all("listing", page), limit, offset, len(rows))


@route(bp, "/listings/<listing_id>/submit-for-review", ["POST"], ("Owner",))
def submit_listing(user_id, role, listing_id):
    v.body()
    listing = svc.lookup("listings", listing_id)
    svc.require_listing_owner(role, user_id, listing)
    if listing["listing_status"] != "DRAFT":
        fail("ERR_LISTING_STATE_INVALID", "Only a DRAFT listing may be submitted.")
    svc.recompute_listing_derived(listing)
    if listing["inspection_photo_zone_count"] != calc.MIN_INSPECTION_PHOTO_ZONES:
        fail("ERR_INSPECTION_PHOTOS_INCOMPLETE",
             "All five inspection photo zones must be documented.")
    today = db.clock.date()
    for doc_type in enums.DATED_DOC_TYPES:
        if svc.verified_document(listing["id"], doc_type, today) is None:
            fail("ERR_REQUIRED_DOCUMENT_MISSING",
                 "A verified, unexpired %s document is required." % doc_type)
    owner = svc.owner_of_listing(listing)
    if owner["status"] != "ACTIVE":
        fail("ERR_OWNER_SUSPENDED", "A suspended owner may not submit a listing.")
    listing["listing_status"] = "IN_REVIEW"
    touch(listing)
    return object_response(ser.dump("listing", listing))


@route(bp, "/listings/<listing_id>/decision", ["POST"], ("PlatformAdmin",))
def decide_listing(user_id, role, listing_id):
    body = v.body()
    decision = v.get_enum(body, "decision", enums.DECISION)
    decision_note = v.get_str(body, "decision_note", min_len=0, required=False)
    listing = svc.lookup("listings", listing_id)
    if listing["listing_status"] != "IN_REVIEW":
        fail("ERR_LISTING_STATE_INVALID", "Only an IN_REVIEW listing may be decided.")
    svc.recompute_listing_derived(listing)
    if decision == "APPROVE":
        if listing["insurance_status"] != "VERIFIED":
            fail("ERR_LISTING_INSURANCE_NOT_VERIFIED",
                 "The listing's insurance must be VERIFIED before approval.")
        listing["listing_status"] = "LISTED"
        listing["decision_note"] = decision_note
        touch(listing)
        owner = svc.owner_of_listing(listing)
        owner["listed_listing_count"] += 1
        touch(owner)
    else:
        listing["listing_status"] = "DRAFT"
        listing["decision_note"] = decision_note
        touch(listing)
    return object_response(ser.dump("listing", listing))


@route(bp, "/listings/<listing_id>/suspend", ["POST"], ("PlatformAdmin",))
def suspend_listing_route(user_id, role, listing_id):
    body = v.body()
    suspend_reason = v.get_str(body, "suspend_reason", min_len=1)
    listing = svc.lookup("listings", listing_id)
    if listing["listing_status"] != "LISTED":
        fail("ERR_LISTING_STATE_INVALID", "Only a LISTED listing may be suspended.")
    svc.suspend_listing(listing, suspend_reason)
    return object_response(ser.dump("listing", listing))


@route(bp, "/listings/<listing_id>/reinstate", ["POST"], ("PlatformAdmin",))
def reinstate_listing(user_id, role, listing_id):
    v.body()
    listing = svc.lookup("listings", listing_id)
    if listing["listing_status"] != "SUSPENDED":
        fail("ERR_LISTING_STATE_INVALID", "Only a SUSPENDED listing may be reinstated.")
    owner = svc.owner_of_listing(listing)
    if owner["owner_penalty_points"] >= calc.OWNER_SUSPENSION_POINT_THRESHOLD:
        fail("ERR_LISTING_STATE_INVALID",
             "The owner's penalty points are at or above the suspension threshold.")
    svc.recompute_listing_derived(listing)
    if listing["insurance_status"] != "VERIFIED":
        fail("ERR_LISTING_INSURANCE_NOT_VERIFIED",
             "The listing's insurance must be VERIFIED before reinstatement.")
    listing["listing_status"] = "LISTED"
    touch(listing)
    owner["listed_listing_count"] += 1
    touch(owner)
    return object_response(ser.dump("listing", listing))


@route(bp, "/listings/<listing_id>/archive", ["POST"], ("Owner", "PlatformAdmin"))
def archive_listing(user_id, role, listing_id):
    v.body()
    listing = svc.lookup("listings", listing_id)
    svc.require_listing_owner(role, user_id, listing)
    if listing["listing_status"] not in ("DRAFT", "SUSPENDED"):
        fail("ERR_LISTING_STATE_INVALID",
             "Only a DRAFT or SUSPENDED listing may be archived.")
    if _live_bookings(listing["id"]):
        fail("ERR_LISTING_STATE_INVALID",
             "A listing with live bookings may not be archived.")
    listing["listing_status"] = "ARCHIVED"
    touch(listing)
    return object_response(ser.dump("listing", listing))


@route(bp, "/listings/<listing_id>/pricing-guidance", ["GET"], ("Owner", "PlatformAdmin"))
def listing_guidance(user_id, role, listing_id):
    listing = svc.lookup("listings", listing_id)
    svc.require_listing_owner(role, user_id, listing)
    return object_response(calc.pricing_guidance(listing))


# -------------------------------------------------------- vehicle documents ----
@route(bp, "/vehicle-documents", ["POST"], ("Owner",))
def create_document(user_id, role):
    body = v.body()
    listing_id = v.get_str(body, "listing_id")
    doc_type = v.get_enum(body, "doc_type", enums.DOC_TYPE)
    zone = v.get_enum(body, "zone", enums.ZONE, required=False)
    expires_on = v.get_date(body, "expires_on", required=False)
    image_ref = v.get_str(body, "image_ref", min_len=1, max_len=200)
    expected_listing_version = v.get_int(body, "expected_listing_version")
    if doc_type == "INSPECTION_PHOTO":
        if zone is None:
            fail("ERR_INVALID_REQUEST", "zone is required for an INSPECTION_PHOTO.")
        if expires_on is not None:
            fail("ERR_INVALID_REQUEST", "expires_on is forbidden for an INSPECTION_PHOTO.")
    else:
        if expires_on is None:
            fail("ERR_INVALID_REQUEST", "expires_on is required for a %s document." % doc_type)
        if zone is not None:
            fail("ERR_INVALID_REQUEST", "zone is forbidden for a %s document." % doc_type)
    listing = svc.lookup("listings", listing_id)
    svc.require_listing_owner(role, user_id, listing)
    if expected_listing_version != listing["version"]:
        fail("ERR_STALE_PARENT_VERSION",
             "expected_listing_version does not match the listing's current version.")

    for prior in svc.listing_documents(listing_id):
        if prior["superseded"] or prior["doc_type"] != doc_type:
            continue
        if doc_type == "INSPECTION_PHOTO" and prior["zone"] != zone:
            continue
        prior["superseded"] = True
        prior["verification_status"] = "SUPERSEDED"
        touch(prior)

    document = new_record(listing_id=listing_id, doc_type=doc_type, zone=zone,
                          expires_on=expires_on, image_ref=image_ref,
                          verification_status="PENDING", superseded=False)
    db.vehicle_documents[document["id"]] = document
    svc.recompute_listing_derived(listing)
    touch(listing)
    return object_response(ser.dump("vehicle_document", document), 201)


@route(bp, "/vehicle-documents/<document_id>", ["GET"],
       ("Owner", "PlatformAdmin", "ClaimsAdjuster"))
def get_document(user_id, role, document_id):
    document = svc.lookup("vehicle_documents", document_id)
    return object_response(ser.dump("vehicle_document", document))


@route(bp, "/vehicle-documents", ["GET"], ("Owner", "PlatformAdmin", "ClaimsAdjuster"))
def list_documents(user_id, role):
    limit, offset = v.pagination()
    listing_id = v.query_str("listing_id")
    doc_type = v.query_enum("doc_type", enums.DOC_TYPE)
    verification_status = v.query_enum("verification_status", enums.VERIFICATION_STATUS)
    rows = creation_order(list(db.vehicle_documents.values()))
    if listing_id is not None:
        rows = [r for r in rows if r["listing_id"] == listing_id]
    if doc_type is not None:
        rows = [r for r in rows if r["doc_type"] == doc_type]
    if verification_status is not None:
        rows = [r for r in rows if r["verification_status"] == verification_status]
    return list_response(ser.dump_all("vehicle_document", paged(rows, limit, offset)),
                         limit, offset, len(rows))


@route(bp, "/vehicle-documents/<document_id>/verify", ["POST"], ("PlatformAdmin",))
def verify_document(user_id, role, document_id):
    v.body()
    document = svc.lookup("vehicle_documents", document_id)
    document["verification_status"] = "VERIFIED"
    touch(document)
    listing = db.listings.get(document["listing_id"])
    if listing is not None:
        svc.recompute_listing_derived(listing)
        touch(listing)
    return object_response(ser.dump("vehicle_document", document))
