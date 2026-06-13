"""CommodityProgram routes (PRD §3.1)."""
from flask import Blueprint

import db
import errors
import response
from middleware import authenticate, require_role, get_json
from services.common import (
    make_common, public, touch, lookup,
    as_number, as_int, as_string, parse_datetime, parse_pagination, paginate,
)
from services import ledger

bp = Blueprint("commodity_programs", __name__)

READ_ROLES = {"RmaAdmin", "Agent", "LossAdjuster"}


@bp.post("/commodity-programs")
def create_program():
    _, role = authenticate()
    require_role(role, {"RmaAdmin"})
    body = get_json()

    crop_code = as_string(body, "crop_code")
    county_code = as_string(body, "county_code")
    crop_year = as_int(body, "crop_year")
    if crop_year < 2000:
        raise errors.err(errors.ERR_INVALID_REQUEST, "crop_year must be >= 2000")
    projected_price = as_number(body, "projected_price")
    if projected_price <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "projected_price must be > 0")
    base_premium_rate = as_number(body, "base_premium_rate")
    if not (0 < base_premium_rate < 1):
        raise errors.err(errors.ERR_INVALID_REQUEST, "base_premium_rate must be strictly between 0 and 1")
    pp_coverage_factor = as_number(body, "pp_coverage_factor")
    if not (0 < pp_coverage_factor <= 1):
        raise errors.err(errors.ERR_INVALID_REQUEST, "pp_coverage_factor must be > 0 and <= 1")
    # Validate datetimes (well-formedness)
    parse_datetime(body, "final_planting_date", required=True)
    parse_datetime(body, "acreage_reporting_deadline", required=True)

    entity = make_common()
    entity.update({
        "crop_code": crop_code,
        "county_code": county_code,
        "crop_year": crop_year,
        "projected_price": projected_price,
        "harvest_price": None,
        "base_premium_rate": base_premium_rate,
        "pp_coverage_factor": pp_coverage_factor,
        "final_planting_date": body["final_planting_date"],
        "acreage_reporting_deadline": body["acreage_reporting_deadline"],
        "harvest_price_published": False,
        "status": "DRAFT",
    })
    db.commodity_programs[entity["id"]] = entity
    return response.success_object(public(entity), 201)


@bp.get("/commodity-programs/<pid>")
def get_program(pid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    entity = lookup(db.commodity_programs, pid)
    return response.success_object(public(entity), 200)


@bp.get("/commodity-programs")
def list_programs():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    from flask import request
    items = list(db.commodity_programs.values())
    if "crop_code" in request.args:
        items = [e for e in items if e["crop_code"] == request.args.get("crop_code")]
    if "county_code" in request.args:
        items = [e for e in items if e["county_code"] == request.args.get("county_code")]
    if "crop_year" in request.args:
        raw = request.args.get("crop_year")
        try:
            cy = int(raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "crop_year must be an integer")
        items = [e for e in items if e["crop_year"] == cy]
    page, total = paginate(items, limit, offset)
    return response.success_array(page, limit, offset, total, 200)


@bp.post("/commodity-programs/<pid>/open")
def open_program(pid):
    _, role = authenticate()
    require_role(role, {"RmaAdmin"})
    entity = lookup(db.commodity_programs, pid)
    if entity["status"] != "DRAFT":
        raise errors.err(errors.ERR_INVALID_STATE, "Program is not in DRAFT status")
    # Preconditions (PRD §3.1)
    if not (entity.get("projected_price") and entity["projected_price"] > 0):
        raise errors.err(errors.ERR_INVALID_STATE, "projected_price must be set and > 0")
    if not entity.get("final_planting_date") or not entity.get("acreage_reporting_deadline"):
        raise errors.err(errors.ERR_INVALID_STATE,
                         "final_planting_date and acreage_reporting_deadline must be set")
    entity["status"] = "OPEN"
    touch(entity)
    return response.success_object(public(entity), 200)


@bp.post("/commodity-programs/<pid>/close")
def close_program(pid):
    _, role = authenticate()
    require_role(role, {"RmaAdmin"})
    entity = lookup(db.commodity_programs, pid)
    if entity["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Program is not in OPEN status")
    # Precondition: no ELECTED election references this program (PRD §3.1)
    for e in db.coverage_elections.values():
        if e["commodity_program_id"] == pid and e["status"] == "ELECTED":
            raise errors.err(errors.ERR_PROGRAM_HAS_OPEN_ELECTIONS,
                             "Program still has ELECTED coverage elections")
    entity["status"] = "CLOSED"
    touch(entity)
    return response.success_object(public(entity), 200)


@bp.post("/commodity-programs/<pid>/publish-harvest-price")
def publish_harvest_price(pid):
    _, role = authenticate()
    require_role(role, {"RmaAdmin"})
    entity = lookup(db.commodity_programs, pid)
    body = get_json()
    harvest_price = as_number(body, "harvest_price")
    entity["harvest_price"] = harvest_price
    entity["harvest_price_published"] = True
    touch(entity)
    return response.success_object(public(entity), 200)
