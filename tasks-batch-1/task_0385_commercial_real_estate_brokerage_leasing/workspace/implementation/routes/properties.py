"""Property and Space endpoints + Space state machine (PRD §3.1, §3.2)."""
from flask import Blueprint, request

from db import db, new_full_record, touch
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from serialize import serialize, serialize_many
from services.access import (resolve, resolve_fk, owns_property, owns_space)
from services.recompute import (recompute_property_available_sf,
                                recompute_all_requirement_match_counts)
from validate import (parse_body, check_str_type, check_int_type,
                      check_number_type, parse_pagination, paginate)

bp = Blueprint("properties", __name__)

VALID_ASSET_CLASSES = {"OFFICE", "RETAIL", "INDUSTRIAL", "FLEX"}


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------
@bp.post("/properties")
def create_property():
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    body = parse_body()
    listing_broker_id = check_str_type(body, "listing_broker_id", required=True)
    name = check_str_type(body, "name", required=True)
    market = check_str_type(body, "market", required=True)
    asset_class = check_str_type(body, "asset_class", required=True)
    total_sf = check_int_type(body, "total_sf", required=True)
    # FK existence (priority 3)
    broker = resolve_fk(db.brokers, listing_broker_id)
    # Ownership: acting ListingBroker must be the broker named (priority 4)
    if listing_broker_id != user_id:
        raise err("ERR_NOT_OWNER", "Acting broker mismatch")
    # constraints (priority 5)
    if not market or market.strip() == "":
        raise err("ERR_INVALID_REQUEST", "market must be non-empty")
    if asset_class not in VALID_ASSET_CLASSES:
        raise err("ERR_INVALID_REQUEST", "Invalid asset_class")
    if total_sf < 1:
        raise err("ERR_INVALID_REQUEST", "total_sf must be >= 1")
    rec = new_full_record({
        "listing_broker_id": listing_broker_id,
        "name": name,
        "market": market,
        "asset_class": asset_class,
        "total_sf": total_sf,
        "available_sf": 0,
    })
    db.properties[rec["id"]] = rec
    return success(serialize("Property", rec), status=201)


@bp.get("/properties/<property_id>")
def get_property(property_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.properties, property_id)
    return success(serialize("Property", rec), status=200)


@bp.get("/properties/<property_id>/spaces")
def list_property_spaces(property_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    resolve(db.properties, property_id)
    limit, offset = parse_pagination()
    items = [s for s in db.spaces.values() if s["property_id"] == property_id]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Space", page), limit, offset, total)


@bp.get("/properties")
def list_properties():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    limit, offset = parse_pagination()
    listing_broker_id = request.args.get("listing_broker_id")
    market = request.args.get("market")
    items = list(db.properties.values())
    if listing_broker_id is not None:
        items = [p for p in items if p["listing_broker_id"] == listing_broker_id]
    if market is not None:
        items = [p for p in items if p["market"] == market]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Property", page), limit, offset, total)


# ---------------------------------------------------------------------------
# Space
# ---------------------------------------------------------------------------
@bp.post("/spaces")
def create_space():
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    body = parse_body()
    property_id = check_str_type(body, "property_id", required=True)
    suite_no = check_str_type(body, "suite_no", required=True)
    rentable_sf = check_int_type(body, "rentable_sf", required=True)
    asking_rent = check_number_type(body, "asking_rent_psf_yr", required=True)
    free_rent_months = check_int_type(body, "free_rent_months",
                                      required=False, default=0)
    ti_allowance = check_number_type(body, "ti_allowance_psf",
                                     required=False, default=0)
    prop = resolve_fk(db.properties, property_id)
    owns_property(user_id, prop)
    # constraints
    if rentable_sf < 1:
        raise err("ERR_INVALID_REQUEST", "rentable_sf must be >= 1")
    if asking_rent <= 0:
        raise err("ERR_INVALID_REQUEST", "asking_rent_psf_yr must be > 0")
    if not (0 <= free_rent_months <= 24):
        raise err("ERR_INVALID_REQUEST", "free_rent_months out of range")
    if ti_allowance < 0:
        raise err("ERR_INVALID_REQUEST", "ti_allowance_psf must be >= 0")
    # suite_no unique per property
    for s in db.spaces.values():
        if s["property_id"] == property_id and s["suite_no"] == suite_no:
            raise err("ERR_INVALID_REQUEST", "suite_no not unique in property")
    rec = new_full_record({
        "property_id": property_id,
        "suite_no": suite_no,
        "rentable_sf": rentable_sf,
        "asking_rent_psf_yr": asking_rent,
        "free_rent_months": free_rent_months,
        "ti_allowance_psf": ti_allowance,
        "status": "DRAFT",
        "held_by_tour_id": None,
    })
    db.spaces[rec["id"]] = rec
    return success(serialize("Space", rec), status=201)


@bp.get("/spaces/<space_id>")
def get_space(space_id):
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    rec = resolve(db.spaces, space_id)
    return success(serialize("Space", rec), status=200)


@bp.get("/spaces")
def list_spaces():
    _, role = authenticate()
    require_role(role, ["BrokerageAdmin", "ListingBroker", "TenantBroker"])
    limit, offset = parse_pagination()
    property_id = request.args.get("property_id")
    status = request.args.get("status")
    held_by_tour_id = request.args.get("held_by_tour_id")
    items = list(db.spaces.values())
    if property_id is not None:
        items = [s for s in items if s["property_id"] == property_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if held_by_tour_id is not None:
        items = [s for s in items if s["held_by_tour_id"] == held_by_tour_id]
    page, total = paginate(items, limit, offset)
    return list_response(serialize_many("Space", page), limit, offset, total)


@bp.post("/spaces/<space_id>/publish")
def publish_space(space_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    sp = resolve(db.spaces, space_id)
    owns_space(user_id, sp)
    if sp["status"] not in ("DRAFT", "OFF_MARKET"):
        raise err("ERR_INVALID_STATE", "Space cannot be published from current state")
    # preconditions (publish from DRAFT requires valid sf/rent — always true here)
    if not (sp["rentable_sf"] >= 1 and sp["asking_rent_psf_yr"] > 0):
        raise err("ERR_SPACE_NOT_AVAILABLE", "Space not publishable")
    sp["status"] = "AVAILABLE"
    touch(sp)
    recompute_property_available_sf(sp["property_id"])
    recompute_all_requirement_match_counts()
    return success(serialize("Space", sp), status=200)


@bp.post("/spaces/<space_id>/withdraw")
def withdraw_space(space_id):
    user_id, role = authenticate()
    require_role(role, ["ListingBroker"])
    sp = resolve(db.spaces, space_id)
    owns_space(user_id, sp)
    if sp["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Space cannot be withdrawn from current state")
    # precondition: no child Listing in UNDER_NEGOTIATION; no space UNDER_LOI
    for lst in db.listings.values():
        if lst["space_id"] == space_id and lst["status"] == "UNDER_NEGOTIATION":
            raise err("ERR_INVALID_STATE", "A child listing is under negotiation")
    # "no space is UNDER_LOI" — interpret as this space; but a space cannot be
    # AVAILABLE and UNDER_LOI simultaneously, so check siblings on same property.
    for other in db.spaces.values():
        if other["property_id"] == sp["property_id"] and other["status"] == "UNDER_LOI":
            raise err("ERR_INVALID_STATE", "A space is under LOI")
    sp["status"] = "OFF_MARKET"
    touch(sp)
    # cascade child Listings in DRAFT/ACTIVE -> WITHDRAWN
    for lst in db.listings.values():
        if lst["space_id"] == space_id and lst["status"] in ("DRAFT", "ACTIVE"):
            lst["status"] = "WITHDRAWN"
            touch(lst)
    recompute_property_available_sf(sp["property_id"])
    recompute_all_requirement_match_counts()
    return success(serialize("Space", sp), status=200)
