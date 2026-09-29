"""HeatTreatFurnace, SaltSprayChamber and FurnaceCampaign endpoints (PRD §3.2, §3.3)."""

from datetime import timedelta

from flask import Blueprint

import calculations as calc
import services as svc
from errors import ApiError
from envelope import ok, ok_list
from routes.helpers import ensure_unique_code, listing
from serialize import campaign_out, chamber_out, furnace_out
from store import base_row, store, touch, with_common
from validate import (auth, filter_arg, get_body, lookup, req_enum, req_int, req_str,
                     req_str_array, require_present, resolve_ref, window_fields)

shop_bp = Blueprint("shop", __name__)

RAMP = timedelta(minutes=calc.RAMP_BUFFER_MINUTES)


# --------------------------------------------------------------------------- #
# HeatTreatFurnace
# --------------------------------------------------------------------------- #
@shop_bp.post("/toolworks/heat-treat-furnaces")
def create_furnace():
    auth("ProductionPlanner", "PlatformAdmin")
    body = get_body()
    furnace_code = req_str(body, "furnace_code")
    max_charge_kg = req_int(body, "max_charge_kg", 1)
    grades = req_str_array(body, "alloy_grades_supported", calc.ALLOY_GRADES)
    ensure_unique_code(store.furnaces, "furnace_code", furnace_code)

    row = with_common(base_row(
        furnace_code=furnace_code,
        max_charge_kg=max_charge_kg,
        alloy_grades_supported=grades,
        status="AVAILABLE",
    ))
    store.furnaces[row["id"]] = row
    return ok(furnace_out(row), 201)


@shop_bp.get("/toolworks/heat-treat-furnaces")
def list_furnaces():
    auth("ProductionPlanner", "QualityEngineer", "PlatformAdmin")
    items, limit, offset, total = listing(
        list(store.furnaces.values()), furnace_out, {"status": filter_arg("status")})
    return ok_list(items, limit, offset, total)


@shop_bp.get("/toolworks/heat-treat-furnaces/<id>")
def get_furnace(id):
    auth("ProductionPlanner", "QualityEngineer", "PlatformAdmin")
    row = lookup(store.furnaces, id, "ERR_FURNACE_NOT_FOUND")
    return ok(furnace_out(row))


@shop_bp.post("/toolworks/heat-treat-furnaces/<id>/status")
def set_furnace_status(id):
    auth("ProductionPlanner", "PlatformAdmin")
    row = lookup(store.furnaces, id, "ERR_FURNACE_NOT_FOUND")
    body = get_body()
    status = req_enum(body, "status", calc.FURNACE_STATUSES)
    if status == row["status"]:
        raise ApiError("ERR_FURNACE_STATUS_UNCHANGED")
    row["status"] = status
    touch(row)
    return ok(furnace_out(row))


# --------------------------------------------------------------------------- #
# SaltSprayChamber
# --------------------------------------------------------------------------- #
@shop_bp.post("/toolworks/salt-spray-chambers")
def create_chamber():
    auth("QualityEngineer", "PlatformAdmin")
    body = get_body()
    chamber_code = req_str(body, "chamber_code")
    coupon_capacity = req_int(body, "coupon_capacity", 1)
    ensure_unique_code(store.chambers, "chamber_code", chamber_code)

    row = with_common(base_row(chamber_code=chamber_code, coupon_capacity=coupon_capacity))
    store.chambers[row["id"]] = row
    return ok(chamber_out(row), 201)


@shop_bp.get("/toolworks/salt-spray-chambers")
def list_chambers():
    auth("QualityEngineer", "ProductionPlanner", "PlatformAdmin")
    items, limit, offset, total = listing(list(store.chambers.values()), chamber_out)
    return ok_list(items, limit, offset, total)


@shop_bp.get("/toolworks/salt-spray-chambers/<id>")
def get_chamber(id):
    auth("QualityEngineer", "ProductionPlanner", "PlatformAdmin")
    row = lookup(store.chambers, id, "ERR_CHAMBER_NOT_FOUND")
    return ok(chamber_out(row))


# --------------------------------------------------------------------------- #
# FurnaceCampaign
# --------------------------------------------------------------------------- #
@shop_bp.post("/toolworks/furnace-campaigns")
def create_campaign():
    auth("ProductionPlanner", "PlatformAdmin")
    body = get_body()

    furnace = resolve_ref(body, "furnace_id", store.furnaces, "ERR_FURNACE_NOT_FOUND")
    lot = resolve_ref(body, "lot_id", store.lots, "ERR_PRODUCTION_LOT_NOT_FOUND")

    require_present(lot, "lot_id")
    require_present(furnace, "furnace_id")
    charge_kg = req_int(body, "charge_kg", 1)
    start, end, raw_start, raw_end = window_fields(body)

    # state preconditions
    if lot["cert_status"] not in ("DRAFT", "IN_TEST"):
        raise ApiError("ERR_LOT_CERT_STATE_INVALID")
    if lot["disposition"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED")
    if furnace["status"] != "AVAILABLE":
        raise ApiError("ERR_FURNACE_UNAVAILABLE")

    # qualification first, then the window, then the charge
    sku = store.skus[lot["sku_id"]]
    if sku["alloy_grade"] not in furnace["alloy_grades_supported"]:
        raise ApiError("ERR_ALLOY_NOT_SUPPORTED")

    for other in svc.sorted_rows([c for c in store.campaigns.values()
                                  if c["furnace_id"] == furnace["id"]]):
        if other["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        if start < other["window_end"] + RAMP and other["window_start"] < end + RAMP:
            raise ApiError("ERR_FURNACE_WINDOW_CONFLICT")

    if charge_kg > furnace["max_charge_kg"]:
        raise ApiError("ERR_FURNACE_CHARGE_EXCEEDED")

    row = with_common(base_row(
        lot_id=lot["id"],
        furnace_id=furnace["id"],
        window_start=start,
        window_end=end,
        window_start_raw=raw_start,
        window_end_raw=raw_end,
        charge_kg=charge_kg,
        buffered_end=end + RAMP,
        soak_minutes=None,
        status="SCHEDULED",
    ))
    store.campaigns[row["id"]] = row
    return ok(campaign_out(row), 201)


@shop_bp.get("/toolworks/furnace-campaigns")
def list_campaigns():
    auth("ProductionPlanner", "QualityEngineer", "PlatformAdmin")
    filters = {
        "lot_id": filter_arg("lot_id"),
        "furnace_id": filter_arg("furnace_id"),
        "status": filter_arg("status"),
    }
    items, limit, offset, total = listing(list(store.campaigns.values()), campaign_out, filters)
    return ok_list(items, limit, offset, total)


@shop_bp.get("/toolworks/furnace-campaigns/<id>")
def get_campaign(id):
    auth("ProductionPlanner", "QualityEngineer", "PlatformAdmin")
    row = lookup(store.campaigns, id, "ERR_CAMPAIGN_NOT_FOUND")
    return ok(campaign_out(row))


@shop_bp.post("/toolworks/furnace-campaigns/<id>/complete")
def complete_campaign(id):
    auth("ProductionPlanner", "PlatformAdmin")
    row = lookup(store.campaigns, id, "ERR_CAMPAIGN_NOT_FOUND")
    body = get_body()
    soak_minutes = req_int(body, "soak_minutes")

    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_CAMPAIGN_STATE_INVALID")
    if soak_minutes < calc.MIN_SOAK_MINUTES:
        raise ApiError("ERR_SOAK_TIME_TOO_SHORT")

    row["soak_minutes"] = soak_minutes
    row["status"] = "COMPLETED"
    touch(row)
    return ok(campaign_out(row))
