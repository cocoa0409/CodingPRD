from flask import Blueprint, request

import db
import validate
import response
import errors
from errors import err
from middleware import get_user_context, require_role, require_ownership
from services import lookup, serialize, paginate, recompute

bp = Blueprint("seats", __name__)

READ_ROLES = ("PlatformAdmin", "Seller", "Buyer", "TrustSafety")


@bp.post("/seats")
def create_seat():
    body = validate.get_json_body()
    listing_id = validate.require_string(body, "listing_id")
    row_label = validate.require_string(body, "row_label")
    seat_number = validate.require_int(body, "seat_number", minimum=1)
    barcode_token = validate.require_string(body, "barcode_token")

    user_id, role = get_user_context()
    require_role(role, ("Seller",))

    listing = lookup.get_listing(listing_id)
    require_ownership(role, user_id, listing["seller_id"])

    # state: seats addable only while DRAFT
    if listing["status"] != "DRAFT":
        raise err(errors.ERR_SEAT_NOT_ADDABLE, "Seats can only be added while listing is DRAFT")

    # uniqueness: barcode_token unique across non-VOID seats
    for s in db.seats.values():
        if s["status"] != "VOID" and s["barcode_token"] == barcode_token:
            raise err(errors.ERR_DUPLICATE_BARCODE, "barcode_token already in use")

    seat = {
        "listing_id": listing_id,
        "section_id": listing["section_id"],
        "row_label": row_label,
        "seat_number": seat_number,
        "barcode_token": barcode_token,
        "status": "AVAILABLE",
        "order_id": None,
    }
    db.stamp_create(seat)
    db.seats[seat["id"]] = seat
    recompute.recompute_listing(listing)
    return response.object_response(serialize.public(seat), 201)


@bp.get("/seats/<seat_id>")
def get_seat(seat_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    seat = lookup.get_seat(seat_id)
    return response.object_response(serialize.public(seat), 200)


@bp.get("/seats")
def list_seats():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    listing_id = request.args.get("listing_id")
    order_id = request.args.get("order_id")
    section_id = request.args.get("section_id")
    records = list(db.seats.values())
    if listing_id is not None:
        records = [s for s in records if s["listing_id"] == listing_id]
    if order_id is not None:
        records = [s for s in records if s.get("order_id") == order_id]
    if section_id is not None:
        records = [s for s in records if s["section_id"] == section_id]
    page, limit, offset, total = paginate.apply_pagination(records)
    return response.array_response(serialize.public_list(page), limit, offset, total)
