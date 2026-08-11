"""Used club listing endpoints."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import raise_err
from middleware import get_auth, require_role
from response import success_response, parse_pagination, apply_pagination
from services.common import touch, get_listing, get_customer
from services.serializers import serialize_used_club_listing

bp = Blueprint("listings", __name__)

ALL_ROLES = {"ShopAdmin", "ShopManager", "FittingSpecialist",
             "RepairTechnician", "Instructor", "Customer"}


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _check_active_customer(user_id):
    customer = db.customers.get(user_id)
    if customer is None:
        raise_err("ERR_CUSTOMER_NOT_FOUND", "customer id does not exist")
    if customer["status"] != "ACTIVE":
        raise_err("ERR_CUSTOMER_SUSPENDED", "customer is suspended")


@bp.get("/used-club-listings/<lid>")
def read_listing(lid):
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    l = get_listing(lid)
    return success_response(serialize_used_club_listing(l))


@bp.get("/used-club-listings")
def list_listings():
    user_id, role = get_auth()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.used_club_listings.values())
    for field in ("appraisal_id", "status", "reserved_by_customer_id",
                  "appraised_by_staff_id"):
        val = request.args.get(field)
        if val is not None:
            items = [l for l in items if l.get(field) == val]
    items.sort(key=lambda l: l["created_at"])
    page, pagination = apply_pagination(items, limit, offset)
    return success_response(
        [serialize_used_club_listing(l) for l in page],
        response_type="array", pagination=pagination,
    )


@bp.post("/used-club-listings/<lid>/reserve")
def reserve_listing(lid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    l = get_listing(lid)
    _check_active_customer(user_id)
    if l["status"] != "LISTED":
        raise_err("ERR_LISTING_NOT_LISTED", "listing is not in LISTED")
    l["status"] = "RESERVED"
    l["reserved_by_customer_id"] = user_id
    l["reserved_until"] = db.logical_now + timedelta(hours=24)
    touch(l)
    return success_response(serialize_used_club_listing(l))


@bp.post("/used-club-listings/<lid>/purchase")
def purchase_listing(lid):
    user_id, role = get_auth()
    require_role(role, {"Customer"})
    l = get_listing(lid)
    _check_active_customer(user_id)
    if l["status"] == "RESERVED":
        if l["reserved_by_customer_id"] != user_id:
            raise_err("ERR_LISTING_RESERVED_BY_OTHER",
                      "listing is reserved by another customer")
    elif l["status"] != "LISTED":
        raise_err("ERR_INVALID_STATE_TRANSITION",
                  "purchase is not defined from the listing's current state")
    l["status"] = "SOLD"
    touch(l)
    return success_response(serialize_used_club_listing(l))


@bp.post("/used-club-listings/<lid>/adjust-price")
def adjust_price_listing(lid):
    user_id, role = get_auth()
    require_role(role, {"ShopManager"})
    data = _body()
    new_price_cents = data.get("new_price_cents")
    if not isinstance(new_price_cents, int) or isinstance(new_price_cents, bool):
        raise_err("ERR_VALIDATION", "new_price_cents must be an integer")
    l = get_listing(lid)
    # State guard before segregation-of-duties (priority 7 before 8)
    if l["status"] != "LISTED":
        raise_err("ERR_LISTING_NOT_LISTED", "listing is not in LISTED")
    if l["appraised_by_staff_id"] == user_id:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "the appraising staff member may not adjust the price")
    l["list_price_cents"] = new_price_cents
    touch(l)
    return success_response(serialize_used_club_listing(l))
