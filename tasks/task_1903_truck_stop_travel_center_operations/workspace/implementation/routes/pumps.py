"""Pump endpoints (PRD 3.1)."""
from flask import Blueprint

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import list_from, list_response, public
from services.core import FUEL_TYPES, new_record, touch
from validate import (
    get_body, query_filter, req_enum_list, req_int, require_path_resource,
)

bp = Blueprint("pumps", __name__)

READ_ROLES = ["GeneralManager", "FuelDeskLead", "Cashier", "ShiftManager"]


@bp.post("/sites/<sid>/pumps")
def create_pump(sid):
    authorized(["GeneralManager", "FuelDeskLead"])
    site = require_path_resource("sites", sid)
    body = get_body()
    pump_number = req_int(body, "pump_number")
    fuel_types = req_enum_list(body, "fuel_types", FUEL_TYPES, non_empty=True)
    for p in db["pumps"].values():
        if p["site_id"] == site["id"] and p["pump_number"] == pump_number:
            raise_error(ERR_INVALID_REQUEST, "pump_number must be unique within the site")
    rec = new_record("pumps", {
        "site_id": site["id"],
        "pump_number": pump_number,
        "fuel_types": fuel_types,
        "status": "IDLE",
    })
    return success_object(public(rec), status=201)


@bp.get("/sites/<sid>/pumps")
def list_pumps(sid):
    authorized(READ_ROLES)
    require_path_resource("sites", sid)
    filters = {
        "site_id": sid,
        "status": query_filter("status", ["IDLE", "IN_USE", "OUT_OF_SERVICE"]),
    }
    return list_response("pumps", filters)


@bp.get("/pumps/<rid>")
def get_pump(rid):
    authorized(READ_ROLES)
    rec = require_path_resource("pumps", rid)
    return success_object(public(rec))


@bp.post("/pumps/<rid>/out-of-service")
def pump_out_of_service(rid):
    authorized(["FuelDeskLead"])
    pump = require_path_resource("pumps", rid)
    if pump["status"] != "IDLE":
        raise_error(ERR_INVALID_STATE, "only an IDLE pump can be taken out of service")
    for sale in db["fuel_sales"].values():
        if (sale["pump_id"] == pump["id"] and sale["status"] != "VOIDED"
                and sale["status"] in ("AUTHORIZED", "FUELING", "PENDING_FINALIZE")):
            raise_error(ERR_INVALID_STATE, "pump has a live fuel sale")
    pump["status"] = "OUT_OF_SERVICE"
    touch(pump)
    return success_object(public(pump))


@bp.post("/pumps/<rid>/return-to-service")
def pump_return_to_service(rid):
    authorized(["FuelDeskLead"])
    pump = require_path_resource("pumps", rid)
    if pump["status"] != "OUT_OF_SERVICE":
        raise_error(ERR_INVALID_STATE, "only an OUT_OF_SERVICE pump can return to service")
    pump["status"] = "IDLE"
    touch(pump)
    return success_object(public(pump))


@bp.get("/pumps/<rid>/fuel-sales")
def pump_fuel_sales(rid):
    authorized(["GeneralManager", "FuelDeskLead", "ShiftManager"])
    pump = require_path_resource("pumps", rid)
    sales = [s for s in db["fuel_sales"].values() if s["pump_id"] == pump["id"]]
    return list_from(sales)
