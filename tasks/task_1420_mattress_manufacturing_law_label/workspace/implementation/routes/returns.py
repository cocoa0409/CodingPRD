"""ReturnRequest endpoints: comfort-exchange / defect return lifecycle."""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors
import middleware
import response
from routes.helpers import as_enum, as_number, as_string, body, require
from services import calc, cascade

bp = Blueprint("returns", __name__)

REASONS = {"COMFORT_EXCHANGE", "DEFECT"}
RESOLUTIONS = {"EXCHANGE", "RECYCLE", "REJECT"}


def return_view(r):
    return {
        "id": r["id"],
        "unit_id": r["unit_id"],
        "retailer_id": r["retailer_id"],
        "reason": r["reason"],
        "measured_sag_inches": r["measured_sag_inches"],
        "resolution": r["resolution"],
        "replacement_unit_id": r["replacement_unit_id"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def get_return(return_id):
    r = db.returns.get(return_id)
    if r is None:
        errors.raise_err(errors.ERR_RETURN_NOT_FOUND, "return not found")
    return r


@bp.route("/returns", methods=["POST"])
def create_return():
    user_id, role = middleware.require_roles(["Retailer"])
    data = body()
    unit_id = as_string(require(data, "unit_id"), "unit_id")
    retailer_id = as_string(require(data, "retailer_id"), "retailer_id")
    reason = as_enum(require(data, "reason"), "reason", REASONS)
    # body-FK existence (PRD section 2.8 tier 3: unit before retailer)
    unit = db.units.get(unit_id)
    if unit is None:
        errors.raise_err(errors.ERR_UNIT_NOT_FOUND, "unit not found")
    # NOTE: no body-supplied retailer existence check here. PRD section 2.8
    # tier 3 only extends to path ids and body-supplied unit references; a
    # retailer_id that does not name an existing retailer falls through to
    # the tier-10 mismatch/identity checks (422).
    # tier 5: unit must be DELIVERED
    if unit["status"] != "DELIVERED":
        errors.raise_err(errors.ERR_UNIT_NOT_DELIVERED, "unit must be DELIVERED")
    # tier 9: 100-night comfort window for comfort exchanges
    if reason == "COMFORT_EXCHANGE":
        delivered = clock.iso_parse(unit["delivered_at"])
        if clock.now() > delivered + timedelta(days=calc.COMFORT_WINDOW_DAYS):
            errors.raise_err(errors.ERR_OUTSIDE_COMFORT_WINDOW, "outside the comfort window")
    # tier 10: referential integrity
    if retailer_id != unit["retailer_id"]:
        errors.raise_err(
            errors.ERR_RETAILER_UNIT_MISMATCH,
            "retailer_id must equal the unit's retailer",
        )
    if role == "Retailer" and retailer_id != user_id:
        errors.raise_err(
            errors.ERR_RETAILER_IDENTITY_MISMATCH,
            "Retailer callers may only reference their own retailer_id",
        )
    ret = {
        "id": db.new_id(),
        "unit_id": unit_id,
        "retailer_id": retailer_id,
        "reason": reason,
        "measured_sag_inches": None,
        "resolution": None,
        "replacement_unit_id": None,
        "status": "REQUESTED",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
    }
    db.put(db.returns, ret)
    return response.success_object(return_view(ret), 201)


@bp.route("/returns", methods=["GET"])
def list_returns():
    middleware.require_roles(middleware.ALL_ROLES)
    items = list(db.returns.values())
    for param in ("unit_id", "retailer_id", "replacement_unit_id", "status"):
        q = request.args.get(param)
        if q is not None:
            items = [r for r in items if r[param] == q]
    items.sort(key=lambda r: r["_seq"])
    return response.success_list([return_view(r) for r in items])


@bp.route("/returns/<returnId>", methods=["GET"])
def get_one_return(returnId):
    middleware.require_roles(middleware.ALL_ROLES)
    r = get_return(returnId)
    return response.success_object(return_view(r))


@bp.route("/returns/<returnId>/receive", methods=["POST"])
def receive_return(returnId):
    middleware.require_roles(["QcInspector"])
    ret = get_return(returnId)
    if ret["status"] != "REQUESTED":
        errors.raise_err(errors.ERR_RETURN_NOT_REQUESTED, "return must be REQUESTED")
    unit = db.units[ret["unit_id"]]
    unit["status"] = "RETURNED"
    cascade.bump(unit)
    ret["status"] = "RECEIVED"
    cascade.bump(ret)
    return response.success_object(return_view(ret))


@bp.route("/returns/<returnId>/inspect", methods=["POST"])
def inspect_return(returnId):
    middleware.require_roles(["QcInspector"])
    ret = get_return(returnId)
    data = body()
    sag = as_number(require(data, "measured_sag_inches"), "measured_sag_inches")
    if ret["status"] != "RECEIVED":
        errors.raise_err(errors.ERR_RETURN_NOT_RECEIVED, "return must be RECEIVED")
    ret["measured_sag_inches"] = sag
    ret["status"] = "INSPECTED"
    cascade.bump(ret)
    return response.success_object(return_view(ret))


@bp.route("/returns/<returnId>/resolve", methods=["POST"])
def resolve_return(returnId):
    middleware.require_roles(["PlantManager"])
    ret = get_return(returnId)
    data = body()
    resolution = as_enum(require(data, "resolution"), "resolution", RESOLUTIONS)
    if ret["status"] != "INSPECTED":
        errors.raise_err(errors.ERR_RETURN_NOT_INSPECTED, "return must be INSPECTED")
    unit = db.units[ret["unit_id"]]
    retailer = db.retailers[ret["retailer_id"]]
    order = db.orders[unit["order_id"]]
    if resolution == "EXCHANGE":
        # tier 8: resolution must match reason
        if ret["reason"] != "COMFORT_EXCHANGE":
            errors.raise_err(
                errors.ERR_RESOLUTION_REASON_MISMATCH,
                "EXCHANGE resolution requires COMFORT_EXCHANGE reason",
            )
        # hop 2: replacement unit + original recovered
        replacement = cascade.manufacture_unit(order, unit["law_label_id"])
        ret["replacement_unit_id"] = replacement["id"]
        unit["status"] = "RECOVERED"
        cascade.bump(unit)
        ret["resolution"] = "EXCHANGE"
        ret["status"] = "RESOLVED_EXCHANGE"
    elif resolution == "RECYCLE":
        # tier 8: retailer enrolled in the take-back program
        if not retailer["recycling_enrolled"]:
            errors.raise_err(errors.ERR_RECYCLING_NOT_ENROLLED, "retailer not recycling-enrolled")
        # hop 2: unit -> SCRAPPED; hop 3: create RecyclingIntake
        unit["status"] = "SCRAPPED"
        cascade.bump(unit)
        declared = cascade.bom_recyclable_mass(unit["model_id"])
        cascade.create_recycling_intake(retailer, declared, unit["id"], "EXCHANGE_RECOVERY")
        ret["resolution"] = "RECYCLE"
        ret["status"] = "RESOLVED_RECYCLED"
    else:  # REJECT
        unit["status"] = "DELIVERED"
        cascade.bump(unit)
        ret["resolution"] = "REJECT"
        ret["status"] = "REJECTED"
    cascade.bump(ret)
    return response.success_object(return_view(ret))
