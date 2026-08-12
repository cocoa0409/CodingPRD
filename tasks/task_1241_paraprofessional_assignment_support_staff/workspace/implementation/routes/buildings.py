"""Building endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import services as svc
from errors import ERR_PLAN_NOT_ACTIVE, ApiError
from middleware import auth_context, require_role
from response import paginate, success
from util import as_num, as_str, bad_request, body_json, need, opt

bp = Blueprint("buildings", __name__)

ADMIN = {"DistrictStaffingAdmin"}
ANY = {"Any"}


def _auth(allowed):
    auth_context()
    require_role(request.headers.get("X-User-Role"), allowed)


@bp.post("/sped-staffing/buildings")
def create_building():
    _auth(ADMIN)
    body = body_json(request)
    plan_id = need(body, "plan_id")
    plan = svc.get_plan(as_str(plan_id, "plan_id"))
    name = as_str(need(body, "name"), "name")
    building_code = as_str(need(body, "building_code"), "building_code")
    hardship = as_num(opt(body, "hardship_factor", 1.0), "hardship_factor")
    if hardship < 0.5 or hardship > 2.0:
        bad_request("hardship_factor must be within 0.5..2.0")
    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError(ERR_PLAN_NOT_ACTIVE, 409,
                       "building creation requires plan DRAFT or ACTIVE")
    for b in db.STORE["buildings"].values():
        if b["plan_id"] == plan["id"] and b["building_code"] == building_code:
            bad_request("building_code must be unique within the plan")
    building = {
        "plan_id": plan["id"],
        "name": name,
        "building_code": building_code,
        "hardship_factor": hardship,
    }
    svc.stamp_new(building)
    db.STORE["buildings"][building["id"]] = building
    return success(svc.ser_building(building), "object", 201)


@bp.get("/sped-staffing/buildings")
def list_buildings():
    _auth(ANY)
    items = []
    plan_id = request.args.get("plan_id")
    for b in svc.sorted_records("buildings"):
        if plan_id is not None and b["plan_id"] != plan_id:
            continue
        items.append(svc.ser_building(b))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/sped-staffing/buildings/<buildingId>")
def get_building(buildingId):
    _auth(ANY)
    building = svc.get_building(buildingId)
    return success(svc.ser_building(building), "object", 200)
