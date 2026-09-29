"""Hotel property registration, portal list and standing changes (PRD §3.1)."""

from flask import Blueprint

import serializers as ser
import validators as V
from auth import authenticate
from envelope import created, ok, ok_list, paginate
from store import ALL_ROLES, STORE, base_record, touch

bp = Blueprint("hotels", __name__, url_prefix="/housing")

STANDINGS = ("ACTIVE", "SUSPENDED")


@bp.post("/hotels")
def create_hotel():
    authenticate(["BureauCoordinator"])
    body = V.json_body()

    name = V.field_str(body, "name", min_len=1)
    distance = V.field_number(body, "distance_to_venue_miles", minimum=0)
    room_tax_pct = V.field_number(body, "room_tax_pct", minimum=0, exclusive_maximum=1)
    total_rooms = V.field_int(body, "total_rooms", minimum=1)
    standing = V.field_enum(body, "standing", STANDINGS, required=False, default="ACTIVE")

    record = base_record()
    record.update(
        {
            "name": name,
            "distance_to_venue_miles": distance,
            "room_tax_pct": room_tax_pct,
            "total_rooms": total_rooms,
            "standing": standing,
        }
    )
    STORE.hotels[record["id"]] = record
    return created(ser.hotel_out(record))


@bp.get("/hotels/<hotel_id>")
def read_hotel(hotel_id):
    authenticate(ALL_ROLES)
    hotel = V.get_hotel(hotel_id)
    return ok(ser.hotel_out(hotel))


@bp.get("/hotels")
def list_hotels():
    authenticate(
        ["BureauCoordinator", "BureauController", "EventOrganizer", "HotelManager", "Attendee"]
    )
    standing = V.enum_arg("standing", STANDINGS)
    limit, offset = V.pagination_args()

    items = list(STORE.hotels.values())
    if standing is not None:
        items = [h for h in items if h["standing"] == standing]
    # PRD §2.3 / §3.1: distance_to_venue_miles ASC then name ASC.
    items.sort(key=lambda h: (h["distance_to_venue_miles"], h["name"], h["_seq"]))
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.hotel_out(h) for h in page], pagination)


@bp.patch("/hotels/<hotel_id>/standing")
def patch_standing(hotel_id):
    authenticate(["BureauCoordinator"])
    body = V.json_body()
    standing = V.field_enum(body, "standing", STANDINGS)
    hotel = V.get_hotel(hotel_id)
    hotel["standing"] = standing
    touch(hotel)
    return ok(ser.hotel_out(hotel))
