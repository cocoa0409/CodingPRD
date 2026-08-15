"""Technician endpoints (onboarding, availability, van stocking)."""
from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state,
                    err_invalid_enum, err_validation)
from middleware import auth, require_technician_self
from response import success
from serializers import serialize
from services.cascades import wall_now
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("technicians", __name__)

CERTS = {"ENGINE", "BRAKES", "ELECTRICAL", "HVAC", "TIRES", "WELDING",
         "DOT_INSPECTION"}
RATE_CLASSES = {"STANDARD", "MASTER"}
SETTABLE_STATUSES = {"OFF_DUTY", "AVAILABLE", "ON_BREAK"}
ALL_STATUSES = {"OFF_DUTY", "AVAILABLE", "ON_BREAK", "ON_DISPATCH"}
ALLOWED_TRANSITIONS = {
    ("OFF_DUTY", "AVAILABLE"),
    ("AVAILABLE", "OFF_DUTY"),
    ("AVAILABLE", "ON_BREAK"),
    ("ON_BREAK", "AVAILABLE"),
}


def _get_tech(technician_id):
    t = store.technicians.get(technician_id)
    if t is None:
        raise err_not_found("Technician not found")
    return t


@bp.route("/roadside/technicians", methods=["POST"])
def create_technician():
    auth(["OpsAdmin"])
    vals = validate_body(request.get_json(silent=True), [
        Field("full_name", "string", required=True),
        Field("employee_code", "string", required=True),
        Field("certifications", "enum_array", required=True, enum=CERTS),
        Field("labor_rate_class", "enum", required=True, enum=RATE_CLASSES),
        Field("home_depot_city", "string", required=True),
    ])
    for t in store.technicians.values():
        if t["employee_code"] == vals["employee_code"]:
            raise ApiError("ERR_DUPLICATE_VIN", "employee_code already exists", 409)
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "full_name": vals["full_name"],
        "employee_code": vals["employee_code"],
        "certifications": vals["certifications"],
        "labor_rate_class": vals["labor_rate_class"],
        "home_depot_city": vals["home_depot_city"],
        "status": "OFF_DUTY",
        "current_dispatch_id": None,
    })
    store.technicians[rec["id"]] = rec
    return success(serialize("technician", rec), status=201)


@bp.route("/roadside/technicians/<technicianId>", methods=["GET"])
def get_technician(technicianId):
    auth(["OpsAdmin", "Dispatcher", "Technician"])
    t = _get_tech(technicianId)
    return success(serialize("technician", t))


@bp.route("/roadside/technicians", methods=["GET"])
def list_technicians():
    auth(["OpsAdmin", "Dispatcher"])
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    cdisp_f = request.args.get("current_dispatch_id")
    items = sorted(store.technicians.values(), key=lambda r: r["_seq"])
    if status_f is not None:
        items = [t for t in items if t["status"] == status_f]
    if cdisp_f is not None:
        items = [t for t in items if t.get("current_dispatch_id") == cdisp_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("technician", t) for t in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/technicians/<technicianId>/set-status", methods=["POST"])
def set_status(technicianId):
    uid, role = auth(["OpsAdmin", "Technician"])
    if role == "Technician":
        require_technician_self(uid, technicianId)
    t = _get_tech(technicianId)
    vals = validate_body(request.get_json(silent=True), [
        Field("to_status", "string", required=True),
    ])
    to_status = vals["to_status"]
    if to_status not in ALL_STATUSES:
        raise err_invalid_enum(
            "to_status must be one of OFF_DUTY, AVAILABLE, ON_BREAK, "
            "ON_DISPATCH")
    # ON_DISPATCH is system-managed: no self-service transition targets it,
    # so a request naming it fails state-machine legality, not shape.
    if (t["status"], to_status) not in ALLOWED_TRANSITIONS:
        raise err_invalid_state(
            f"Technician cannot move from {t['status']} to {to_status}")
    t["status"] = to_status
    touch(t, wall_now())
    return success(serialize("technician", t))


@bp.route("/roadside/technicians/<technicianId>/van-stock", methods=["POST"])
def create_van_stock(technicianId):
    auth(["OpsAdmin"])
    t = _get_tech(technicianId)
    vals = validate_body(request.get_json(silent=True), [
        Field("part_number", "string", required=True),
        Field("description", "string", required=True),
        Field("part_class", "enum", required=True,
              enum={"ENGINE", "COOLING", "BRAKE", "AIR_SYSTEM", "ELECTRICAL",
                    "LIGHTING", "TIRE", "HVAC", "FILTERS"}),
        Field("qty_on_hand", "int", min_val=0),
        Field("unit_cost_cents", "int", required=True, min_val=0),
        Field("unit_retail_cents", "int", required=True, min_val=0),
        Field("reorder_point", "int", min_val=0),
    ])
    for item in store.van_stock.values():
        if (item["technician_id"] == t["id"]
                and item["part_number"] == vals["part_number"]):
            raise err_validation(
                "part_number must be unique per technician")
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "technician_id": t["id"],
        "part_number": vals["part_number"],
        "description": vals["description"],
        "part_class": vals["part_class"],
        "qty_on_hand": vals.get("qty_on_hand", 0),
        "unit_cost_cents": vals["unit_cost_cents"],
        "unit_retail_cents": vals["unit_retail_cents"],
        "reorder_point": vals.get("reorder_point", 2),
    })
    store.van_stock[rec["id"]] = rec
    return success(serialize("van_item", rec), status=201)
