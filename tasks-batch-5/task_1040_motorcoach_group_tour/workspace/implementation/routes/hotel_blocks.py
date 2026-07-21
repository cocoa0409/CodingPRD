"""HotelBlock endpoints."""
from flask import Blueprint, request

import services
from store import db
from web import (
    authenticate,
    get_body,
    created,
    ok,
    ok_list,
    parse_pagination,
    req_str,
    req_int,
)

bp = Blueprint("hotel_blocks", __name__)


@bp.post("/api/hotel-blocks")
def create_hotel_block():
    authenticate({"OpsManager"})
    body = get_body()
    departure_id = req_str(body, "departure_id")
    hotel_name = req_str(body, "hotel_name")
    city = req_str(body, "city")
    room_count = req_int(body, "room_count", min_val=0)
    nights = req_int(body, "nights", min_val=1)
    rate = req_int(body, "rate_per_room_night_cents", min_val=0)
    services.get_or_404(db.departures, departure_id)
    blk = services.create_hotel_block(departure_id, hotel_name, city, room_count, nights, rate)
    return created(services.serialize(blk))


@bp.get("/api/hotel-blocks/<hotel_block_id>")
def get_hotel_block(hotel_block_id):
    authenticate("ALL")
    blk = services.get_or_404(db.hotel_blocks, hotel_block_id)
    return ok(services.serialize(blk))


@bp.get("/api/hotel-blocks")
def list_hotel_blocks():
    authenticate("ALL")
    limit, offset = parse_pagination()
    items = list(db.hotel_blocks.values())
    departure_id = request.args.get("departure_id")
    if departure_id is not None:
        items = [b for b in items if b["departure_id"] == departure_id]
    page, total = services.paginate(items, limit, offset)
    return ok_list([services.serialize(b) for b in page], total, limit, offset)


@bp.post("/api/hotel-blocks/<hotel_block_id>/confirm")
def confirm_hotel_block(hotel_block_id):
    authenticate({"OpsManager"})
    blk = services.get_or_404(db.hotel_blocks, hotel_block_id)
    services.confirm_hotel_block(blk)
    return ok(services.serialize(blk))


@bp.post("/api/hotel-blocks/<hotel_block_id>/release")
def release_hotel_block(hotel_block_id):
    authenticate({"OpsManager"})
    blk = services.get_or_404(db.hotel_blocks, hotel_block_id)
    services.release_hotel_block(blk)
    return ok(services.serialize(blk))
