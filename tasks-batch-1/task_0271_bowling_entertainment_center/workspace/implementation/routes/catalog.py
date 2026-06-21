"""Configuration & catalog resources: RateCard, Lane, Bay, PartyPackage,
FoodItem, RentalItem (PRD §3.1)."""
from flask import Blueprint, request

from db import db, new_common, touch
from errors import err
from middleware import get_identity, require_role
from response import success, array
from services import serialize
from services.util import (
    get_body, parse_pagination, paginate, lookup,
    as_int, as_str, as_bool, as_enum,
)

bp = Blueprint("catalog", __name__)

ALL_ROLES = {"Customer", "FrontDesk", "LeagueAdmin", "CenterManager"}


# ------------------------------------------------------------------ RateCard
@bp.post("/rate-cards")
def create_rate_card():
    _, role = get_identity()
    require_role(role, {"CenterManager"})
    body = get_body()
    name = as_str(body, "name")
    per_game_cents = as_int(body, "per_game_cents", minimum=0)
    per_hour_cents = as_int(body, "per_hour_cents", minimum=0)
    block_minutes = as_int(body, "block_minutes", required=False, default=60, minimum=1)
    peak_multiplier_bps = as_int(body, "peak_multiplier_bps", required=False, default=10000, minimum=10000)
    peak_start_hour = as_int(body, "peak_start_hour", required=False, default=18, minimum=0, maximum=23)
    peak_end_hour = as_int(body, "peak_end_hour", required=False, default=23, minimum=0, maximum=23)
    deposit_pct_bps = as_int(body, "deposit_pct_bps", required=False, default=2000, minimum=0, maximum=10000)

    e = new_common()
    e.update({
        "name": name,
        "per_game_cents": per_game_cents,
        "per_hour_cents": per_hour_cents,
        "block_minutes": block_minutes,
        "peak_multiplier_bps": peak_multiplier_bps,
        "peak_start_hour": peak_start_hour,
        "peak_end_hour": peak_end_hour,
        "deposit_pct_bps": deposit_pct_bps,
    })
    db.rate_cards[e["id"]] = e
    return success(serialize.rate_card(e), status=201)


@bp.get("/rate-cards/<id>")
def get_rate_card(id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    e = lookup(db.rate_cards, id, "rate card")
    return success(serialize.rate_card(e))


@bp.get("/rate-cards")
def list_rate_cards():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    page, meta = paginate(list(db.rate_cards.values()), limit, offset)
    return array([serialize.rate_card(e) for e in page], pagination=meta)


# ---------------------------------------------------------------------- Lane
@bp.post("/lanes")
def create_lane():
    _, role = get_identity()
    require_role(role, {"CenterManager"})
    body = get_body()
    number = as_int(body, "number", minimum=1)
    max_bowlers = as_int(body, "max_bowlers", required=False, default=6, minimum=1)
    for existing in db.lanes.values():
        if existing["number"] == number:
            raise err("ERR_DUPLICATE_LANE_NUMBER", "Lane number already in use")
    e = new_common()
    e.update({"number": number, "max_bowlers": max_bowlers, "status": "IN_SERVICE"})
    db.lanes[e["id"]] = e
    return success(serialize.lane(e), status=201)


@bp.get("/lanes/<id>")
def get_lane(id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    e = lookup(db.lanes, id, "lane")
    return success(serialize.lane(e))


@bp.get("/lanes")
def list_lanes():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.lanes.values())
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    page, meta = paginate(items, limit, offset)
    return array([serialize.lane(e) for e in page], pagination=meta)


@bp.post("/lanes/<id>/set-status")
def set_lane_status(id):
    _, role = get_identity()
    require_role(role, {"CenterManager"})
    e = lookup(db.lanes, id, "lane")
    body = get_body()
    status = as_enum(body, "status", {"IN_SERVICE", "OUT_OF_SERVICE"})
    e["status"] = status
    touch(e)
    return success(serialize.lane(e))


# ----------------------------------------------------------------------- Bay
@bp.post("/bays")
def create_bay():
    _, role = get_identity()
    require_role(role, {"CenterManager"})
    body = get_body()
    name = as_str(body, "name")
    capacity = as_int(body, "capacity", required=False, default=12, minimum=1)
    cleanup_buffer_minutes = as_int(body, "cleanup_buffer_minutes", required=False, default=15, minimum=0)
    e = new_common()
    e.update({
        "name": name,
        "capacity": capacity,
        "cleanup_buffer_minutes": cleanup_buffer_minutes,
        "status": "IN_SERVICE",
    })
    db.bays[e["id"]] = e
    return success(serialize.bay(e), status=201)


@bp.get("/bays/<id>")
def get_bay(id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    e = lookup(db.bays, id, "bay")
    return success(serialize.bay(e))


@bp.get("/bays")
def list_bays():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.bays.values())
    status = request.args.get("status")
    if status:
        items = [e for e in items if e["status"] == status]
    page, meta = paginate(items, limit, offset)
    return array([serialize.bay(e) for e in page], pagination=meta)


@bp.post("/bays/<id>/set-status")
def set_bay_status(id):
    _, role = get_identity()
    require_role(role, {"CenterManager"})
    e = lookup(db.bays, id, "bay")
    body = get_body()
    status = as_enum(body, "status", {"IN_SERVICE", "OUT_OF_SERVICE"})
    e["status"] = status
    touch(e)
    return success(serialize.bay(e))


# -------------------------------------------------------------- PartyPackage
@bp.post("/party-packages")
def create_party_package():
    _, role = get_identity()
    require_role(role, {"CenterManager"})
    body = get_body()
    name = as_str(body, "name")
    base_cents = as_int(body, "base_cents", minimum=0)
    included_guests = as_int(body, "included_guests", minimum=1)
    extra_guest_cents = as_int(body, "extra_guest_cents", minimum=0)
    max_guests = as_int(body, "max_guests", minimum=included_guests)
    included_lane_hours = as_int(body, "included_lane_hours", required=False, default=2, minimum=0)
    e = new_common()
    e.update({
        "name": name,
        "base_cents": base_cents,
        "included_guests": included_guests,
        "extra_guest_cents": extra_guest_cents,
        "max_guests": max_guests,
        "included_lane_hours": included_lane_hours,
    })
    db.party_packages[e["id"]] = e
    return success(serialize.party_package(e), status=201)


@bp.get("/party-packages/<id>")
def get_party_package(id):
    _, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    e = lookup(db.party_packages, id, "party package")
    return success(serialize.party_package(e))


@bp.get("/party-packages")
def list_party_packages():
    _, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    limit, offset = parse_pagination()
    page, meta = paginate(list(db.party_packages.values()), limit, offset)
    return array([serialize.party_package(e) for e in page], pagination=meta)


# ------------------------------------------------------------------ FoodItem
@bp.post("/food-items")
def create_food_item():
    _, role = get_identity()
    require_role(role, {"CenterManager"})
    body = get_body()
    name = as_str(body, "name")
    unit_cents = as_int(body, "unit_cents", minimum=0)
    taxable = as_bool(body, "taxable", required=False, default=True)
    e = new_common()
    e.update({"name": name, "unit_cents": unit_cents, "taxable": taxable})
    db.food_items[e["id"]] = e
    return success(serialize.food_item(e), status=201)


@bp.get("/food-items/<id>")
def get_food_item(id):
    _, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    e = lookup(db.food_items, id, "food item")
    return success(serialize.food_item(e))


@bp.get("/food-items")
def list_food_items():
    _, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    limit, offset = parse_pagination()
    page, meta = paginate(list(db.food_items.values()), limit, offset)
    return array([serialize.food_item(e) for e in page], pagination=meta)


# ---------------------------------------------------------------- RentalItem
@bp.post("/rental-items")
def create_rental_item():
    _, role = get_identity()
    require_role(role, {"CenterManager"})
    body = get_body()
    kind = as_enum(body, "kind", {"SHOES", "BALL", "BUMPER"})
    label = as_str(body, "label")
    unit_price_cents = as_int(body, "unit_price_cents", minimum=0)
    total_count = as_int(body, "total_count", minimum=0)
    e = new_common()
    e.update({
        "kind": kind,
        "label": label,
        "unit_price_cents": unit_price_cents,
        "total_count": total_count,
        "out_on_rent_count": 0,
        "available_count": total_count,
    })
    db.rental_items[e["id"]] = e
    return success(serialize.rental_item(e), status=201)


@bp.get("/rental-items/<id>")
def get_rental_item(id):
    _, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    e = lookup(db.rental_items, id, "rental item")
    return success(serialize.rental_item(e))


@bp.get("/rental-items")
def list_rental_items():
    _, role = get_identity()
    require_role(role, {"Customer", "FrontDesk", "CenterManager"})
    limit, offset = parse_pagination()
    items = list(db.rental_items.values())
    kind = request.args.get("kind")
    if kind:
        items = [e for e in items if e["kind"] == kind]
    page, meta = paginate(items, limit, offset)
    return array([serialize.rental_item(e) for e in page], pagination=meta)
