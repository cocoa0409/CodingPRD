"""Crew and Equipment endpoints (PRD 3.2). Status is computed on read."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import authorized
from response import success_object
from routes.helpers import serialize, list_response, get_one
from services.core import new_record
from validate import get_body, req_str, opt_str, req_num, req_enum, opt_bool

bp = Blueprint("resources", __name__)

CREW_TYPES = {"OVERHEAD", "UNDERGROUND", "STORM"}
EQUIPMENT_KINDS = {"BUCKET_TRUCK", "DIGGER_DERRICK", "TRENCHER", "REEL_TRAILER"}


@bp.post("/crews")
def create_crew():
    authorized(["CONTRACTOR_PM"])
    body = get_body()
    crew_code = req_str(body, "crew_code")
    crew_type = req_enum(body, "crew_type", CREW_TYPES)
    base_rate_per_hour = req_num(body, "base_rate_per_hour", positive=True)
    home_depot = opt_str(body, "home_depot", None)
    for c in db["crews"].values():
        if c["crew_code"] == crew_code:
            raise_error(ERR_INVALID_REQUEST,
                        f"crew_code already exists: {crew_code}")
    rec = new_record("crews", {
        "crew_code": crew_code,
        "crew_type": crew_type,
        "base_rate_per_hour": base_rate_per_hour,
        "home_depot": home_depot,
    })
    return success_object(serialize("crews", rec), status=201)


@bp.get("/crews")
def list_crews():
    filters = {
        "crew_type": request.args.get("crew_type"),
        "status": request.args.get("status"),
    }
    return list_response("crews", filters)


@bp.get("/crews/<crew_id>")
def get_crew(crew_id):
    return get_one("crews", crew_id)


@bp.post("/equipment")
def create_equipment():
    authorized(["CONTRACTOR_PM"])
    body = get_body()
    equipment_code = req_str(body, "equipment_code")
    kind = req_enum(body, "kind", EQUIPMENT_KINDS)
    daily_rate = req_num(body, "daily_rate", positive=True)
    maintenance_flag = opt_bool(body, "maintenance_flag", False)
    for e in db["equipment"].values():
        if e["equipment_code"] == equipment_code:
            raise_error(ERR_INVALID_REQUEST,
                        f"equipment_code already exists: {equipment_code}")
    rec = new_record("equipment", {
        "equipment_code": equipment_code,
        "kind": kind,
        "daily_rate": daily_rate,
        "maintenance_flag": maintenance_flag,
    })
    return success_object(serialize("equipment", rec), status=201)


@bp.get("/equipment")
def list_equipment():
    filters = {
        "kind": request.args.get("kind"),
        "status": request.args.get("status"),
    }
    return list_response("equipment", filters)


@bp.get("/equipment/<equipment_id>")
def get_equipment(equipment_id):
    return get_one("equipment", equipment_id)
