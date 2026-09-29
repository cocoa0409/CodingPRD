"""Food and beverage exclusivity and outside catering exceptions (PRD 3.7)."""

from flask import Blueprint

import calc
import lookups
import validate
from db import db
from errors import err
from middleware import body, endpoint, filter_rows, touch
from response import entity_response
from routes.common import (
    ARRANGEMENT_TYPES,
    EXCEPTION_REASONS,
    body_fk,
    listing,
    require_coi_current,
    require_posture,
)

bp = Blueprint("catering", __name__)

LIVE_ARRANGEMENT_STATES = ("PROPOSED", "APPROVED", "CLOSED")


@bp.post("/bookings/<booking_id>/catering-arrangements")
@endpoint("EventServicesManager")
def propose_arrangement(booking_id):
    booking = lookups.fetch("booking", booking_id)
    payload = body()

    # ladder step 5 then step 7
    vendor = body_fk(payload, "vendor_id", "vendor")
    arrangement_type = validate.req_enum(payload, "arrangement_type", ARRANGEMENT_TYPES)
    estimated = validate.req_int(payload, "estimated_fnb_cents", minimum=0)
    exception_reason = validate.opt_enum(payload, "exception_reason", EXCEPTION_REASONS)

    # ladder step 10, step 12, then the exclusivity gates of step 14
    require_posture(booking)
    for existing in lookups.catering_of_booking(booking["id"]):
        if existing["status"] in LIVE_ARRANGEMENT_STATES:
            raise err("ERR_CATERING_ALREADY_EXISTS")
    require_coi_current(vendor)
    if vendor["service_category"] != "CATERING":
        raise err("ERR_VENDOR_CATEGORY_MISMATCH")
    in_house_vendor = bool(vendor.get("is_in_house_caterer"))
    if arrangement_type == "IN_HOUSE" and not in_house_vendor:
        raise err("ERR_CATERING_EXCLUSIVITY_VIOLATION")
    if arrangement_type == "OUTSIDE_EXCEPTION" and in_house_vendor:
        raise err("ERR_CATERING_EXCLUSIVITY_VIOLATION")
    if arrangement_type == "OUTSIDE_EXCEPTION" and exception_reason is None:
        raise err("ERR_OUTSIDE_CATERING_REASON_REQUIRED")
    if arrangement_type == "IN_HOUSE" and exception_reason is not None:
        raise err("ERR_OUTSIDE_CATERING_REASON_REQUIRED")

    arrangement = db.insert(
        "catering",
        {
            "booking_id": booking["id"],
            "vendor_id": vendor["id"],
            "arrangement_type": arrangement_type,
            "exception_reason": exception_reason,
            "estimated_fnb_cents": estimated,
            "actual_fnb_cents": None,
            "buyout_fee_cents": 0,
            "status": "PROPOSED",
        },
    )
    return entity_response(arrangement, 201)


@bp.get("/catering-arrangements")
@endpoint("VenueAdmin", "EventServicesManager", "SettlementAnalyst")
def list_arrangements():
    rows = filter_rows(
        "catering",
        {"booking_id": "booking_id", "vendor_id": "vendor_id", "status": "status"},
    )
    return listing(rows)


@bp.get("/catering-arrangements/<arrangement_id>")
@endpoint("VenueAdmin", "EventServicesManager", "SettlementAnalyst")
def read_arrangement(arrangement_id):
    return entity_response(lookups.fetch("catering", arrangement_id))


@bp.post("/catering-arrangements/<arrangement_id>/approve")
@endpoint("EventServicesManager")
def approve_arrangement(arrangement_id):
    arrangement = lookups.fetch("catering", arrangement_id)
    if arrangement["status"] != "PROPOSED":
        raise err("ERR_CATERING_STATE_INVALID")
    booking = db.bookings.get(arrangement["booking_id"])
    require_posture(booking)

    if arrangement["arrangement_type"] == "OUTSIDE_EXCEPTION":
        if arrangement.get("exception_reason") is None:
            raise err("ERR_OUTSIDE_CATERING_REASON_REQUIRED")
        vendor = db.vendors.get(arrangement["vendor_id"])
        if vendor is not None and vendor.get("is_in_house_caterer"):
            raise err("ERR_CATERING_EXCLUSIVITY_VIOLATION")

    arrangement["status"] = "APPROVED"
    arrangement["buyout_fee_cents"] = calc.fnb_buyout_fee(
        arrangement, arrangement["estimated_fnb_cents"]
    )
    touch(arrangement)
    return entity_response(arrangement)


@bp.post("/catering-arrangements/<arrangement_id>/deny")
@endpoint("EventServicesManager")
def deny_arrangement(arrangement_id):
    arrangement = lookups.fetch("catering", arrangement_id)
    if arrangement["status"] != "PROPOSED":
        raise err("ERR_CATERING_STATE_INVALID")
    arrangement["status"] = "DENIED"
    arrangement["buyout_fee_cents"] = 0
    touch(arrangement)
    return entity_response(arrangement)


@bp.patch("/catering-arrangements/<arrangement_id>")
@endpoint("EventServicesManager")
def record_actual_fnb(arrangement_id):
    arrangement = lookups.fetch("catering", arrangement_id)
    payload = body()
    arrangement["actual_fnb_cents"] = validate.req_int(payload, "actual_fnb_cents", minimum=0)
    touch(arrangement)
    return entity_response(arrangement)
