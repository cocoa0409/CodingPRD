"""Recovery cylinders and the reclaim chain (PRD 3.2)."""
from decimal import Decimal

from flask import Blueprint, request

import constants
import db
import response
import util
import validate
from errors import ApiError, invalid
from middleware import COMPLIANCE_MANAGER, endpoint, read_endpoint
from services import guards

bp = Blueprint("cylinders", __name__)

ZERO_1 = Decimal("0.0")


@bp.post("/cylinders")
@endpoint([COMPLIANCE_MANAGER])
def create_cylinder():
    payload = validate.body()
    store_id = validate.req_id(payload, "store_id")
    refrigerant_type_id = validate.req_id(payload, "refrigerant_type_id")
    cylinder_serial = validate.req_str(payload, "cylinder_serial")
    nominal_capacity_lbs = validate.req_decimal(payload, "nominal_capacity_lbs")
    if nominal_capacity_lbs <= Decimal("0"):
        raise invalid("nominal_capacity_lbs must be greater than 0")
    initial_contents_lbs = validate.req_decimal(payload, "initial_contents_lbs",
                                                minimum=Decimal("0"))
    fill_limit_lbs = util.q1(nominal_capacity_lbs * constants.CYLINDER_FILL_FRACTION)
    if initial_contents_lbs > fill_limit_lbs:
        raise invalid("initial_contents_lbs must not exceed the 80 percent fill limit")
    db.require("stores", store_id)
    db.require("refrigerant_types", refrigerant_type_id)
    guards.require_unique("cylinders", "cylinder_serial", cylinder_serial)
    cylinder = db.new_entity()
    cylinder.update({
        "store_id": store_id,
        "refrigerant_type_id": refrigerant_type_id,
        "cylinder_serial": cylinder_serial,
        "nominal_capacity_lbs": nominal_capacity_lbs,
        "fill_limit_lbs": fill_limit_lbs,
        "initial_contents_lbs": initial_contents_lbs,
        "current_contents_lbs": initial_contents_lbs,
        "shipped_for_reclaim_lbs": ZERO_1,
        "disposition": "VIRGIN",
        "shipped_on": None,
        "reclaimer_name": None,
        "reclaim_certificate_number": None,
        "reclaimed_quantity_lbs": None,
        "purity_verified": None,
        "reclaim_issued_on": None,
    })
    db.insert("cylinders", cylinder)
    return response.created(cylinder)


@bp.get("/cylinders")
@read_endpoint
def list_cylinders():
    filters = {
        "store_id": request.args.get("store_id"),
        "refrigerant_type_id": request.args.get("refrigerant_type_id"),
        "disposition": request.args.get("disposition"),
    }
    return response.listing(db.values("cylinders"), filters)


@bp.get("/cylinders/<cylinder_id>")
@read_endpoint
def get_cylinder(cylinder_id):
    return response.ok(db.require("cylinders", cylinder_id))


@bp.post("/cylinders/<cylinder_id>/reclaim-shipment")
@endpoint([COMPLIANCE_MANAGER])
def ship_cylinder(cylinder_id):
    payload = validate.body()
    reclaimer_name = validate.req_str(payload, "reclaimer_name")
    cylinder = db.require("cylinders", cylinder_id)
    guards.require_state(cylinder["disposition"] == "RECOVERED"
                         and cylinder["current_contents_lbs"] > ZERO_1)
    snap = db.snapshot(cylinder)
    cylinder["shipped_for_reclaim_lbs"] = util.q1(
        cylinder["shipped_for_reclaim_lbs"] + cylinder["current_contents_lbs"])
    cylinder["current_contents_lbs"] = ZERO_1
    cylinder["shipped_on"] = db.now()
    cylinder["reclaimer_name"] = reclaimer_name
    cylinder["disposition"] = "SENT_FOR_RECLAIM"
    db.commit(cylinder, snap)
    return response.ok(cylinder)


@bp.post("/cylinders/<cylinder_id>/reclaim-certification")
@endpoint([COMPLIANCE_MANAGER])
def certify_cylinder(cylinder_id):
    payload = validate.body()
    certificate_number = validate.req_str(payload, "reclaim_certificate_number")
    reclaimed_quantity_lbs = validate.req_decimal(payload, "reclaimed_quantity_lbs",
                                                  minimum=Decimal("0"))
    purity_verified = validate.req_bool(payload, "purity_verified")
    reclaim_issued_on = validate.req_instant(payload, "reclaim_issued_on")
    reclaimer_name = validate.opt_str(payload, "reclaimer_name")
    cylinder = db.require("cylinders", cylinder_id)
    guards.require_state(cylinder["disposition"] == "SENT_FOR_RECLAIM")
    guards.require_not_after_clock(reclaim_issued_on)
    if reclaimed_quantity_lbs > cylinder["shipped_for_reclaim_lbs"]:
        raise ApiError("ERR_RECLAIM_QUANTITY_EXCEEDS_SHIPPED")
    if not purity_verified:
        raise ApiError("ERR_RECLAIM_PURITY_NOT_VERIFIED")
    snap = db.snapshot(cylinder)
    cylinder["current_contents_lbs"] = util.q1(reclaimed_quantity_lbs)
    cylinder["shipped_for_reclaim_lbs"] = util.q1(
        cylinder["shipped_for_reclaim_lbs"] - reclaimed_quantity_lbs)
    cylinder["reclaim_certificate_number"] = certificate_number
    cylinder["reclaimed_quantity_lbs"] = util.q1(reclaimed_quantity_lbs)
    cylinder["purity_verified"] = purity_verified
    cylinder["reclaim_issued_on"] = reclaim_issued_on
    if reclaimer_name is not None:
        cylinder["reclaimer_name"] = reclaimer_name
    cylinder["disposition"] = "RECLAIMED"
    db.commit(cylinder, snap)
    return response.ok(cylinder)
