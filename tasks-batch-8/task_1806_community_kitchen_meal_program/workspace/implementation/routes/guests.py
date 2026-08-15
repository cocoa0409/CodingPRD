"""GuestProfile (PRD 3.5)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE,
)
from helpers import (
    get_body, req_field, req_int, opt_list, opt_field, opt_num, check_enum_subset,
    stamp_new, paginate, apply_filters, get_or_404, touch,
)
from middleware import get_caller, check_role_allowed
from response import success_object, success_list
from routes.common import public, public_list

bp = Blueprint("guests", __name__)

ALLERGENS = {"GLUTEN", "DAIRY", "EGG", "SOY", "PEANUT", "TREE_NUT", "FISH", "SHELLFISH", "SESAME"}
DIETARY = {"VEGETARIAN", "VEGAN", "HALAL", "KOSHER_STYLE", "LOW_SODIUM", "DIABETIC_FRIENDLY"}
KM = ["KitchenManager"]


@bp.route("/kitchen/guests", methods=["POST"])
def create_guest():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager"])

    full_name = req_field(body, "full_name", str)
    household_size = req_int(body, "household_size", minimum=1)
    allergens = opt_list(body, "allergens", [])
    dietary_preferences = opt_list(body, "dietary_preferences", [])
    check_enum_subset(allergens, ALLERGENS, "allergens")
    check_enum_subset(dietary_preferences, DIETARY, "dietary_preferences")
    delivery_address = opt_field(body, "delivery_address", str, None, allow_null=True)
    delivery_distance_km = opt_num(body, "delivery_distance_km", None)

    rec = stamp_new({
        "full_name": full_name,
        "household_size": household_size,
        "allergens": allergens,
        "dietary_preferences": dietary_preferences,
        "delivery_address": delivery_address,
        "delivery_distance_km": delivery_distance_km,
        "visits_count": 0,
        "status": "ACTIVE",
    })
    db["guests"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/kitchen/guests/<gid>", methods=["GET"])
def get_guest(gid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Guest"])
    rec = get_or_404("guests", gid)
    return success_object(public(rec))


@bp.route("/kitchen/guests/<gid>/meal-orders", methods=["GET"])
def list_guest_orders(gid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Guest"])
    get_or_404("guests", gid)
    items = [o for o in db["meal_orders"].values() if o["guest_id"] == gid]
    items = apply_filters(items, request.args, ["fulfillment_status"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/guests/<gid>/flag", methods=["POST"])
def flag_guest(gid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    g = get_or_404("guests", gid)
    if g["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, f"cannot flag from {g['status']}")
    g["status"] = "FLAGGED"
    touch(g)
    return success_object(public(g))


@bp.route("/kitchen/guests/<gid>/unflag", methods=["POST"])
def unflag_guest(gid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    g = get_or_404("guests", gid)
    if g["status"] != "FLAGGED":
        raise_error(ERR_INVALID_STATE, f"cannot unflag from {g['status']}")
    g["status"] = "ACTIVE"
    touch(g)
    return success_object(public(g))


@bp.route("/kitchen/guests/<gid>/deactivate", methods=["POST"])
def deactivate_guest(gid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    g = get_or_404("guests", gid)
    if g["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, f"cannot deactivate from {g['status']}")
    for o in db["meal_orders"].values():
        if o["guest_id"] == gid and o["fulfillment_status"] == "RESERVED":
            raise_error(ERR_INVALID_STATE,
                        "guest has RESERVED orders and cannot be deactivated")
    g["status"] = "INACTIVE"
    touch(g)
    return success_object(public(g))
