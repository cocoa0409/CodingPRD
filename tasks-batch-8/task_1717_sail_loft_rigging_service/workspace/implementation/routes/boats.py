"""Boat endpoints."""

from flask import Blueprint, request

import db
import util
from middleware import require_roles
from response import success_object, success_list
from services import domain

bp = Blueprint("boats", __name__)

READ_ROLES = ("LoftManager", "Sailmaker", "Measurer", "Rigger", "Customer")
RACING_CLASSES = ("NONE", "J70", "J105", "TP52", "ORC", "PHRF")


@bp.post("/lofts/customers/<customerId>/boats")
def create_boat(customerId):
    require_roles("LoftManager")
    cust = domain.get_customer_or_404(customerId)
    body = util.get_body()
    boat_name = util.as_string(util.require_field(body, "boat_name"), "boat_name")
    hull_length_m = util.as_number(util.require_field(body, "hull_length_m"), "hull_length_m")
    racing_class = util.as_enum(util.require_field(body, "racing_class"), "racing_class", RACING_CLASSES)
    install_raw = util.require_field(body, "standing_rigging_install_date")
    install_dt = util.parse_iso_datetime(install_raw, "standing_rigging_install_date")
    running_hours = util.as_int(util.opt_field(body, "running_rigging_hours_accumulated", 0), "running_rigging_hours_accumulated")
    boat = util.stamp_new({
        "customer_id": cust["id"],
        "boat_name": boat_name,
        "hull_length_m": hull_length_m,
        "racing_class": racing_class,
        "mast_status": "STEPPED",
        "standing_rigging_install_date": install_raw,
        "running_rigging_hours_accumulated": running_hours,
        "status": "ACTIVE",
    })
    db.boats[boat["id"]] = boat
    return success_object(domain.serialize(boat), 201)


@bp.get("/lofts/customers/<customerId>/boats")
def list_customer_boats(customerId):
    require_roles(*READ_ROLES)
    domain.get_customer_or_404(customerId)
    limit, offset = util.pagination_params()
    items = [b for b in db.boats.values() if b["customer_id"] == customerId]
    items = util.sort_by_created(items)
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(b) for b in page], limit, offset, total)


@bp.get("/lofts/boats")
def list_boats():
    require_roles(*READ_ROLES)
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.boats.values()))
    items = util.filter_exact(items, "customer_id", request.args.get("customer_id"))
    items = util.filter_exact(items, "status", request.args.get("status"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(b) for b in page], limit, offset, total)


@bp.get("/lofts/boats/<boatId>")
def get_boat(boatId):
    require_roles(*READ_ROLES)
    boat = domain.get_boat_or_404(boatId)
    return success_object(domain.serialize(boat))
