"""Planogram endpoints (scaffold §1.5; activation OCC on Location.version per §1.2.1)."""
from flask import Blueprint, request
import db
from middleware import get_auth, require_role, require_operator_ownership
from response import success_object, success_list, parse_pagination
from util import get_json_body, req_string, req_array, req_int, stamp_new, touch
from errors import (
    ApiError, ERR_LOCATION_NOT_FOUND, ERR_PLANOGRAM_NOT_FOUND, ERR_PRODUCT_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE,
    ERR_PLANOGRAM_NOT_DRAFT, ERR_PLANOGRAM_NOT_ACTIVE, ERR_PRODUCT_DISCONTINUED,
    ERR_STALE_VERSION,
)
from services import pricing
import clock

bp = Blueprint("planograms", __name__)


def view(pg):
    return {k: v for k, v in pg.items()}


def _location_operator_id(pg):
    loc = db.locations.get(pg["location_id"])
    return loc["operator_id"] if loc else None


def _validate_slots(slots, location, check_active=False):
    """Slots shape + uniqueness + product existence + location-type eligibility.
    check_active=True also enforces product ACTIVE (activate flow, tier 11)."""
    seen = set()
    for row in slots:
        if not isinstance(row, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "slots rows must be objects")
        slot_code = row.get("slot_code")
        if not isinstance(slot_code, str) or not slot_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "slot_code required")
        product_id = row.get("product_id")
        if not isinstance(product_id, str) or not product_id:
            raise ApiError(ERR_INVALID_REQUEST, 400, "product_id required")
        par = row.get("par_level_units")
        if isinstance(par, bool) or not isinstance(par, int):
            raise ApiError(ERR_INVALID_REQUEST, 400, "par_level_units must be an integer")
        if par < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "par_level_units must be >= 0")
        vend = row.get("vend_price_cents")
        if isinstance(vend, bool) or not isinstance(vend, int):
            raise ApiError(ERR_INVALID_REQUEST, 400, "vend_price_cents must be an integer")
        if vend < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "vend_price_cents must be >= 0")
        if product_id in seen:
            raise ApiError(ERR_INVALID_REQUEST, 400, "product_id must be unique within slots")
        seen.add(product_id)
        product = db.products.get(product_id)
        if product is None:
            raise ApiError(ERR_PRODUCT_NOT_FOUND, 404, "Product id does not exist")
        if check_active and product["status"] != "ACTIVE":
            raise ApiError(ERR_PRODUCT_DISCONTINUED, 422, "Product is DISCONTINUED")
        if location["location_type"] not in product["eligible_location_types"]:
            raise ApiError(
                ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE, 422,
                "Product's eligible_location_types does not include the location's location_type",
            )


@bp.post("/wholesale/planograms")
def create_planogram():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["OperatorManager"])
    location_id = req_string(body, "location_id")
    name = req_string(body, "name")
    slots = req_array(body, "slots")
    # Body-reference existence: location (tier 6) then ownership (tier 5 note: ownership
    # evaluated after target known to exist; for create, target = location chain).
    location = db.locations.get(location_id)
    if location is None:
        raise ApiError(ERR_LOCATION_NOT_FOUND, 404, "Location id does not exist")
    require_operator_ownership(role, user_id, location["operator_id"])
    _validate_slots(slots, location, check_active=False)
    new_slots = []
    for row in slots:
        new_slots.append({
            "slot_code": row["slot_code"],
            "product_id": row["product_id"],
            "par_level_units": row["par_level_units"],
            "vend_price_cents": row["vend_price_cents"],
            "cull_flag": False,
        })
    pg = stamp_new({
        "location_id": location_id,
        "name": name,
        "slots": new_slots,
        "status": "DRAFT",
        "activated_at": None,
    })
    db.planograms[pg["id"]] = pg
    return success_object(view(pg), 201)


@bp.get("/wholesale/planograms")
def list_planograms():
    get_auth()
    limit, offset = parse_pagination(request.args)
    loc_f = request.args.get("location_id")
    items = list(db.planograms.values())
    if loc_f is not None:
        items = [p for p in items if p["location_id"] == loc_f]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    return success_list([view(p) for p in items[offset:offset + limit]], limit, offset, total)


@bp.get("/wholesale/planograms/<planogramId>")
def get_planogram(planogramId):
    get_auth()
    pg = db.planograms.get(planogramId)
    if pg is None:
        raise ApiError(ERR_PLANOGRAM_NOT_FOUND, 404, "Planogram id does not exist")
    return success_object(view(pg))


@bp.post("/wholesale/planograms/<planogramId>/activate")
def activate_planogram(planogramId):
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["OperatorManager"])
    pg = db.planograms.get(planogramId)
    if pg is None:
        raise ApiError(ERR_PLANOGRAM_NOT_FOUND, 404, "Planogram id does not exist")
    require_operator_ownership(role, user_id, _location_operator_id(pg))
    # OCC (tier: from-state 7 then OCC per PRD §2.7; scaffold lists DRAFT check first)
    if pg["status"] != "DRAFT":
        raise ApiError(ERR_PLANOGRAM_NOT_DRAFT, 409, "activate requires planogram DRAFT")
    expected = body.get("expected_location_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_location_version must be an integer")
    location = db.locations[pg["location_id"]]
    if expected != location["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_location_version does not equal the location's current version")
    # Referenced-entity state: products exist / ACTIVE / eligible (tier 11)
    _validate_slots(pg["slots"], location, check_active=True)
    # Side effects: supersede incumbent, stamp activated_at, bump Location.version
    incumbent = pricing.active_planogram_for_location(pg["location_id"])
    if incumbent is not None:
        incumbent["status"] = "ARCHIVED"
        touch(incumbent)
    pg["status"] = "ACTIVE"
    pg["activated_at"] = clock.now_iso()
    touch(pg)
    touch(location)  # Location.version increments by 1
    return success_object(view(pg))


@bp.post("/wholesale/planograms/<planogramId>/cull-evaluate")
def cull_evaluate(planogramId):
    user_id, role = get_auth()
    get_json_body(required=False)
    require_role(role, ["OperatorManager"])
    pg = db.planograms.get(planogramId)
    if pg is None:
        raise ApiError(ERR_PLANOGRAM_NOT_FOUND, 404, "Planogram id does not exist")
    require_operator_ownership(role, user_id, _location_operator_id(pg))
    if pg["status"] != "ACTIVE":
        raise ApiError(ERR_PLANOGRAM_NOT_ACTIVE, 409, "cull-evaluate requires planogram ACTIVE")
    pricing.cull_evaluate(pg)
    return success_object(view(pg))
