"""Vehicle routes (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import get_json_body, require_auth
from response import ok_array, ok_object, paginate_params, slice_page
from services.validation import (
    lookup_fk_or_404,
    lookup_path_or_404,
    require_enum,
    require_fields,
    require_int,
    require_string,
)

bp = Blueprint("vehicles", __name__)

TPMS_TYPES = {"DIRECT", "INDIRECT", "NONE"}


@bp.post("/vehicles")
def create_vehicle():
    require_auth(["ServiceAdvisor", "Customer"])()
    body = get_json_body()
    require_fields(
        body,
        ["customer_id", "make", "model", "model_year", "oe_tire_size",
         "rim_diameter_in", "tpms_type"],
    )
    customer_id = require_string(body["customer_id"], "customer_id")
    make = require_string(body["make"], "make")
    model = require_string(body["model"], "model")
    model_year = require_int(body["model_year"], "model_year",
                             min_value=1980, max_value=2030)
    oe_tire_size = require_string(body["oe_tire_size"], "oe_tire_size")
    rim_diameter_in = require_int(body["rim_diameter_in"], "rim_diameter_in",
                                  min_value=13, max_value=24)
    tpms_type = require_enum(body["tpms_type"], TPMS_TYPES, "tpms_type")

    with db.mutation_lock:
        lookup_fk_or_404(db.customers, customer_id, "Customer")
        vehicle = {
            "customer_id": customer_id,
            "make": make,
            "model": model,
            "model_year": model_year,
            "oe_tire_size": oe_tire_size,
            "rim_diameter_in": rim_diameter_in,
            "tpms_type": tpms_type,
        }
        db.stamp_common(vehicle)
        db.vehicles[vehicle["id"]] = vehicle
        return ok_object(vehicle, 201)


@bp.get("/vehicles/<vid>")
def get_vehicle(vid: str):
    require_auth(["ServiceAdvisor", "Customer"])()
    vehicle = lookup_path_or_404(db.vehicles, vid, "Vehicle")
    return ok_object(vehicle, 200)


@bp.get("/vehicles")
def list_vehicles():
    require_auth(["ServiceAdvisor", "Customer"])()
    limit, offset = paginate_params(request.args)
    items = list(db.vehicles.values())
    if "customer_id" in request.args:
        items = [v for v in items if v["customer_id"] == request.args["customer_id"]]
    items.sort(key=db.created_then_seq)
    page, total = slice_page(items, limit, offset)
    return ok_array(page, limit, offset, total, 200)
