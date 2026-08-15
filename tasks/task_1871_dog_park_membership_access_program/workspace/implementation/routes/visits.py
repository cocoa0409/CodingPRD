"""ParkVisit endpoints: gate check-in, check-out, list, read."""
from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_AREA_NOT_FOUND, ERR_DOG_NOT_FOUND,
    ERR_GUEST_PASS_NOT_FOUND, ERR_VISIT_NOT_FOUND, ERR_NOT_OWNER,
    ERR_DOG_NOT_VERIFIED, ERR_GUEST_PASS_NOT_REDEEMABLE,
    ERR_VACCINATION_EXPIRED, ERR_DOG_SIZE_AREA_MISMATCH,
    ERR_ALREADY_CHECKED_IN, ERR_AREA_CLOSED, ERR_AREA_AT_CAPACITY,
    ERR_VISIT_NOT_OPEN,
)
from helpers import (
    get_body, req_string, parse_date, today, now_iso, now_dt,
    parse_pagination, slice_page,
)
from middleware import require_auth
from response import ok
from services import domain

bp = Blueprint("visits", __name__)

VISIT_STATUSES = ("OPEN", "CLOSED", "FORCE_CLOSED")


@bp.route("/dog-park/visits/check-in", methods=["POST"])
def check_in():
    uid, role = require_auth(["Member", "ParkAdmin"])
    body = get_body()
    area_id = req_string(body, "area_id")
    dog_id = body.get("dog_id")
    pass_id = body.get("guest_pass_id")
    if dog_id is not None and not isinstance(dog_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "dog_id must be a string")
    if pass_id is not None and not isinstance(pass_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "guest_pass_id must be a string")
    dog_present = bool(dog_id)
    pass_present = bool(pass_id)
    if dog_present == pass_present:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Exactly one of dog_id and guest_pass_id must be supplied")
    # Stage 6 existence: area first, then dog/pass.
    area = store.areas.get(area_id)
    if area is None:
        raise ApiError(ERR_AREA_NOT_FOUND, 404, "Park area not found")

    dog = None
    guest_pass = None
    if dog_present:
        dog = store.dogs.get(dog_id)
        if dog is None:
            raise ApiError(ERR_DOG_NOT_FOUND, 404, "Dog not found")
        # Ownership (Member role; ParkAdmin exempt).
        if role == "Member" and dog["member_id"] != uid:
            raise ApiError(ERR_NOT_OWNER, 403,
                           "Members may only check in their own dogs")
        # Stage 8 state.
        if dog["verification_status"] != "VERIFIED":
            raise ApiError(ERR_DOG_NOT_VERIFIED, 409,
                           "Check-in requires a VERIFIED dog")
        # Stage 9 vaccination currency.
        expires = parse_date(dog["vaccination_expires_on"])
        if expires is None or expires < today():
            raise ApiError(ERR_VACCINATION_EXPIRED, 422,
                           "Dog vaccination has expired")
        # Stage 10 business constraints.
        if dog["size_class"] != area["size_class_restriction"]:
            raise ApiError(ERR_DOG_SIZE_AREA_MISMATCH, 409,
                           "Dog size class does not match the area restriction")
        if any(v["dog_id"] == dog_id and v["status"] == "OPEN"
               for v in store.visits.values()):
            raise ApiError(ERR_ALREADY_CHECKED_IN, 409,
                           "Dog already has an OPEN visit")
        visit_member_id = uid if role == "Member" else dog["member_id"]
        size_class = dog["size_class"]
    else:
        guest_pass = store.guest_passes.get(pass_id)
        if guest_pass is None:
            raise ApiError(ERR_GUEST_PASS_NOT_FOUND, 404, "Guest pass not found")
        if role == "Member" and guest_pass["sponsor_member_id"] != uid:
            raise ApiError(ERR_NOT_OWNER, 403,
                           "Members may only redeem passes they sponsored")
        # Stage 8 state.
        if guest_pass["status"] != "ISSUED":
            raise ApiError(ERR_GUEST_PASS_NOT_REDEEMABLE, 409,
                           "Guest pass is not in ISSUED status")
        # Stage 10 business constraints.
        if guest_pass["guest_dog_size_class"] != area["size_class_restriction"]:
            raise ApiError(ERR_DOG_SIZE_AREA_MISMATCH, 409,
                           "Guest dog size class does not match the area restriction")
        visit_member_id = uid if role == "Member" else guest_pass["sponsor_member_id"]

    # Stage 11 temporal: no ACTIVE closure on the target area.
    if any(c["area_id"] == area_id and c["status"] == "ACTIVE"
           for c in store.closures.values()):
        raise ApiError(ERR_AREA_CLOSED, 409,
                       "An ACTIVE closure exists on the target area")
    if guest_pass is not None:
        valid = parse_date(guest_pass["valid_on"])
        if valid != today():
            raise ApiError(ERR_GUEST_PASS_NOT_REDEEMABLE, 409,
                           "Guest pass valid_on does not equal the current date")

    # Stage 12 quota — always last.
    if domain.occupancy(area_id) >= domain.effective_capacity(area):
        raise ApiError(ERR_AREA_AT_CAPACITY, 409,
                       "Area is at its effective capacity")

    visit = domain.new_entity(store.visits, {
        "member_id": visit_member_id,
        "dog_id": dog_id if dog_present else None,
        "guest_pass_id": pass_id if pass_present else None,
        "area_id": area_id,
        "checked_in_at": now_iso(),
        "checked_out_at": None,
        "status": "OPEN",
        "close_reason": None,
    })
    visit["_checked_in_dt"] = now_dt()
    if guest_pass is not None:
        guest_pass["status"] = "REDEEMED"
        domain.touch(guest_pass)
    return ok(domain.public(visit), 201)


@bp.route("/dog-park/visits/<visitId>/check-out", methods=["POST"])
def check_out(visitId):
    uid, role = require_auth(["Member", "ParkAdmin"])
    visit = store.visits.get(visitId)
    if visit is None:
        raise ApiError(ERR_VISIT_NOT_FOUND, 404, "Visit not found")
    if role == "Member" and visit["member_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403,
                       "Members may only check out their own visits")
    if visit["status"] != "OPEN":
        raise ApiError(ERR_VISIT_NOT_OPEN, 409,
                       "Check-out requires an OPEN visit")
    visit["status"] = "CLOSED"
    visit["close_reason"] = "VOLUNTARY"
    visit["checked_out_at"] = now_iso()
    domain.touch(visit)
    return ok(domain.public(visit))


@bp.route("/dog-park/visits", methods=["GET"])
def list_visits():
    require_auth(["Steward", "ParkAdmin"])
    status_filter = request.args.get("status")
    if status_filter is not None and status_filter not in VISIT_STATUSES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid status filter")
    limit, offset = parse_pagination()
    filters = {
        "member_id": request.args.get("member_id"),
        "dog_id": request.args.get("dog_id"),
        "area_id": request.args.get("area_id"),
        "guest_pass_id": request.args.get("guest_pass_id"),
    }
    items = []
    for v in store.visits.values():
        if status_filter is not None and v["status"] != status_filter:
            continue
        if any(fval is not None and v[fkey] != fval
               for fkey, fval in filters.items()):
            continue
        items.append(v)
    page, meta = slice_page(items, limit, offset)
    return ok([domain.public(v) for v in page], 200, meta)


@bp.route("/dog-park/visits/<visitId>", methods=["GET"])
def get_visit(visitId):
    uid, role = require_auth(["Member", "Steward", "ParkAdmin"])
    visit = store.visits.get(visitId)
    if visit is None:
        raise ApiError(ERR_VISIT_NOT_FOUND, 404, "Visit not found")
    if role == "Member" and visit["member_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403,
                       "Members may only read their own visits")
    return ok(domain.public(visit))
