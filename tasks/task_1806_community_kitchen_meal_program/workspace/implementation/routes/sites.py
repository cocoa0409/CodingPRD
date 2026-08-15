"""Sites (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_CONSTRAINT_VIOLATION
from helpers import (
    get_body, req_field, req_int, opt_num, stamp_new, paginate, apply_filters, get_or_404,
)
from middleware import get_caller, check_role_allowed
from response import success_object, success_list
from routes.common import public, public_list

bp = Blueprint("sites", __name__)

ALL = ["ProgramAdmin", "KitchenManager", "FoodSafetyOfficer", "Volunteer", "Guest"]


@bp.route("/kitchen/sites", methods=["POST"])
def create_site():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin"])

    name = req_field(body, "name", str)
    dine_in_capacity = req_int(body, "dine_in_capacity", minimum=1)
    togo_capacity_per_window = req_int(body, "togo_capacity_per_window", minimum=1)
    delivery_radius_km = opt_num(body, "delivery_radius_km")
    if delivery_radius_km is None:
        from errors import ERR_VALIDATION
        raise_error(ERR_VALIDATION, "missing required field: delivery_radius_km")

    for s in db["sites"].values():
        if s["name"] == name:
            raise_error(ERR_CONSTRAINT_VIOLATION, f"site name already exists: {name}")

    rec = stamp_new({
        "name": name,
        "dine_in_capacity": dine_in_capacity,
        "togo_capacity_per_window": togo_capacity_per_window,
        "delivery_radius_km": delivery_radius_km,
        "equipment_posture": "OPERATIONAL",
        "status": "OPEN",
    })
    db["sites"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/kitchen/sites", methods=["GET"])
def list_sites():
    caller = get_caller()
    check_role_allowed(caller, ALL)
    items = apply_filters(list(db["sites"].values()), request.args, ["status"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/sites/<sid>", methods=["GET"])
def get_site(sid):
    caller = get_caller()
    check_role_allowed(caller, ALL)
    rec = get_or_404("sites", sid)
    return success_object(public(rec))


@bp.route("/kitchen/sites/<sid>/equipment-assets", methods=["GET"])
def list_site_equipment(sid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer"])
    get_or_404("sites", sid)
    items = [a for a in db["equipment_assets"].values() if a["site_id"] == sid]
    items = apply_filters(items, request.args, ["status", "equipment_class"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/sites/<sid>/food-batches", methods=["GET"])
def list_site_batches(sid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "FoodSafetyOfficer"])
    get_or_404("sites", sid)
    items = [b for b in db["food_batches"].values() if b["site_id"] == sid]
    items = apply_filters(items, request.args, ["status", "source_type"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)


@bp.route("/kitchen/sites/<sid>/volunteer-shifts", methods=["GET"])
def list_site_shifts(sid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer"])
    get_or_404("sites", sid)
    items = [s for s in db["volunteer_shifts"].values() if s["site_id"] == sid]
    items = apply_filters(items, request.args, ["status", "volunteer_id"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list(public_list(page), total, limit, offset)
