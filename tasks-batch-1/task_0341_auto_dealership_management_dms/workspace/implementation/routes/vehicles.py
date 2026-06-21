import re

from flask import Blueprint, request

import db
import response
from errors import err
from middleware import require_roles
from routes.lookup import get_path
from services import calc, serialize
from util import (base_record, get_json_body, paginate, parse_dt, parse_pagination,
                  require_enum, require_int, require_str, touch)

bp = Blueprint("vehicles", __name__)

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")  # 17 uppercase alnum excluding I, O, Q


def _valid_vin(vin):
    return isinstance(vin, str) and bool(_VIN_RE.match(vin))


@bp.post("/vehicles")
@require_roles("InventoryClerk")
def create_vehicle():
    body = get_json_body()
    vin = require_str(body, "vin")
    if not _valid_vin(vin):
        raise err("ERR_INVALID_REQUEST", "VIN must be 17 uppercase alphanumerics excluding I, O, Q")
    condition = require_enum(body, "condition", ("NEW", "USED"))
    make = require_str(body, "make")
    model = require_str(body, "model")
    model_year = require_int(body, "model_year")
    msrp_cents = require_int(body, "msrp_cents", minimum=0)
    list_price_cents = require_int(body, "list_price_cents", minimum=0)

    # VIN uniqueness (priority 6) — after well-formedness.
    for v in db.vehicles.values():
        if v["vin"] == vin:
            raise err("ERR_VIN_DUPLICATE", "VIN already exists in inventory")

    rec = base_record()
    rec.update({
        "vin": vin,
        "condition": condition,
        "make": make,
        "model": model,
        "model_year": model_year,
        "msrp_cents": msrp_cents,
        "list_price_cents": list_price_cents,
        "status": "AVAILABLE",
        "acquired_from_trade_in_id": None,
        "active_floor_plan_line_id": None,
    })
    db.vehicles[rec["id"]] = rec
    return response.success(serialize.vehicle(rec), status=201)


@bp.get("/vehicles/<vid>")
@require_roles("InventoryClerk", "SalesManager", "FinanceManager", "ServiceAdvisor", "TitleClerk")
def get_vehicle(vid):
    rec = get_path(db.vehicles, vid)
    return response.success(serialize.vehicle(rec))


@bp.get("/vehicles")
@require_roles("InventoryClerk", "SalesManager", "FinanceManager", "ServiceAdvisor", "TitleClerk")
def list_vehicles():
    limit, offset = parse_pagination()
    items = list(db.vehicles.values())
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    trade_in_id = request.args.get("acquired_from_trade_in_id")
    if trade_in_id is not None:
        items = [v for v in items if v.get("acquired_from_trade_in_id") == trade_in_id]
    page, total, has_more = paginate(items, limit, offset)
    return response.success_list([serialize.vehicle(v) for v in page], limit, offset, total, has_more)


@bp.post("/vehicles/<vid>/recondition-complete")
@require_roles("InventoryClerk")
def recondition_complete(vid):
    rec = get_path(db.vehicles, vid)
    if rec["status"] != "RECON":
        raise err("ERR_INVALID_STATE", "Vehicle is not in RECON")
    rec["status"] = "AVAILABLE"
    touch(rec)
    return response.success(serialize.vehicle(rec))


@bp.post("/vehicles/<vid>/floor-plan-lines")
@require_roles("InventoryClerk")
def create_floor_plan_line(vid):
    rec = get_path(db.vehicles, vid)
    body = get_json_body()
    lender_name = require_str(body, "lender_name")
    principal_cents = require_int(body, "principal_cents", gt=0)
    annual_rate_bps = require_int(body, "annual_rate_bps", minimum=0)
    floored_on = parse_dt(body, "floored_on")
    expected = require_int(body, "expected_vehicle_version")

    # OCC check (priority 8) — after well-formedness.
    if expected != rec["version"]:
        raise err("ERR_STALE_VERSION", "Vehicle version has advanced")

    # Supersede prior ACTIVE line.
    prior = calc.active_floor_plan_line(vid)
    if prior is not None:
        prior["status"] = "SUPERSEDED"

    line = base_record()
    line.update({
        "vehicle_id": vid,
        "lender_name": lender_name,
        "principal_cents": principal_cents,
        "annual_rate_bps": annual_rate_bps,
        "floored_on": body["floored_on"],
        "principal_outstanding_cents": principal_cents,
        "curtailments_applied": 0,
        "status": "ACTIVE",
    })
    db.floor_plan_lines[line["id"]] = line

    rec["active_floor_plan_line_id"] = line["id"]
    touch(rec)
    return response.success(serialize.floor_plan_line(line), status=201)


@bp.get("/vehicles/<vid>/floor-plan-lines")
@require_roles("InventoryClerk", "FinanceManager")
def list_vehicle_floor_plan_lines(vid):
    get_path(db.vehicles, vid)
    limit, offset = parse_pagination()
    items = [l for l in db.floor_plan_lines.values() if l["vehicle_id"] == vid]
    page, total, has_more = paginate(items, limit, offset)
    return response.success_list(
        [serialize.floor_plan_line(l) for l in page], limit, offset, total, has_more
    )
