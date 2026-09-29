"""ProductionLot endpoints (PRD §3.2, §3.5)."""

from flask import Blueprint

import calculations as calc
import services as svc
from errors import ApiError
from envelope import ok, ok_list
from routes.helpers import ensure_unique_code, listing
from serialize import lot_out, run_out
from store import base_row, store, touch, with_common
from validate import (auth, filter_arg, get_body, lookup, req_enum, req_int, req_str,
                     require_present, resolve_ref)

lots_bp = Blueprint("lots", __name__)

READ_ROLES = ["ProductionPlanner", "QualityEngineer", "ChannelManager", "PlatformAdmin"]
PLANNER = ["ProductionPlanner", "PlatformAdmin"]

STAGE_ORDER = calc.PROCESS_STATUSES


@lots_bp.post("/toolworks/production-lots")
def create_lot():
    auth(*PLANNER)
    body = get_body()

    sku = resolve_ref(body, "sku_id", store.skus, "ERR_TOOL_SKU_NOT_FOUND")
    require_present(sku, "sku_id")
    lot_code = req_str(body, "lot_code")
    unit_count = req_int(body, "unit_count", 1)
    specimen_pool_total = req_int(body, "specimen_pool_total", 1)
    ensure_unique_code(store.lots, "lot_code", lot_code)

    row = with_common(base_row(
        sku_id=sku["id"],
        lot_code=lot_code,
        unit_count=unit_count,
        specimen_pool_total=specimen_pool_total,
        specimens_available=specimen_pool_total,
        specimens_committed=0,
        specimens_consumed=0,
        process_status="FORGED",
        cert_status="DRAFT",
        disposition="IN_PROCESS",
        hardness_index_sample=None,
        hardness_index_pooled=None,
        proof_torque_required_nm=sku["proof_torque_required_nm"],
        rework_cycle_count=0,
        certified_at=None,
    ))
    store.lots[row["id"]] = row
    return ok(lot_out(row), 201)


@lots_bp.get("/toolworks/production-lots")
def list_lots():
    auth(*READ_ROLES)
    filters = {
        "process_status": filter_arg("process_status"),
        "cert_status": filter_arg("cert_status"),
        "disposition": filter_arg("disposition"),
    }
    items, limit, offset, total = listing(list(store.lots.values()), lot_out, filters)
    return ok_list(items, limit, offset, total)


@lots_bp.get("/toolworks/production-lots/<id>")
def get_lot(id):
    auth(*READ_ROLES)
    row = lookup(store.lots, id, "ERR_PRODUCTION_LOT_NOT_FOUND")
    return ok(lot_out(row))


@lots_bp.post("/toolworks/production-lots/<id>/advance")
def advance_lot(id):
    auth(*PLANNER)
    lot = lookup(store.lots, id, "ERR_PRODUCTION_LOT_NOT_FOUND")
    body = get_body()
    target = req_enum(body, "target_process_status", STAGE_ORDER)

    if lot["cert_status"] not in ("DRAFT", "IN_TEST"):
        raise ApiError("ERR_LOT_CERT_STATE_INVALID")

    current_index = STAGE_ORDER.index(lot["process_status"])
    if STAGE_ORDER.index(target) != current_index + 1:
        raise ApiError("ERR_LOT_PROCESS_STATE_INVALID")

    if lot["disposition"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED")

    if target == "HEAT_TREATED":
        completed = [c for c in svc.lot_campaigns(lot["id"]) if c["status"] == "COMPLETED"]
        if not completed:
            raise ApiError("ERR_HEAT_TREAT_NOT_COMPLETED")

    lot["process_status"] = target
    touch(lot)
    return ok(lot_out(lot))


@lots_bp.post("/toolworks/production-lots/<id>/certify")
def certify_lot(id):
    auth("QualityEngineer", "PlatformAdmin")
    lot = lookup(store.lots, id, "ERR_PRODUCTION_LOT_NOT_FOUND")
    get_body()

    if lot["cert_status"] != "IN_TEST":
        raise ApiError("ERR_LOT_CERT_STATE_INVALID")
    if lot["process_status"] != "ASSEMBLED":
        raise ApiError("ERR_LOT_PROCESS_STATE_INVALID")
    if lot["disposition"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED")

    sku = store.skus[lot["sku_id"]]
    runs = svc.lot_runs(lot["id"])
    passed_types = {r["test_type"] for r in runs if r["status"] == "PASSED"}
    for test_type in calc.MANDATORY_TESTS[sku["tool_family"]]:
        if test_type not in passed_types:
            raise ApiError("ERR_MANDATORY_TEST_MISSING")

    if any(r["status"] == "FAILED" for r in runs):
        raise ApiError("ERR_FAILED_TEST_PRESENT")

    svc.recompute_hardness(lot)
    required = (calc.HARDNESS_MIN_HRC[sku["alloy_grade"]]
                + calc.CHANNEL_HARDNESS_MARGIN[sku["channel"]])
    pooled = lot["hardness_index_pooled"]
    if pooled is None or pooled < required:
        raise ApiError("ERR_HARDNESS_MARGIN_NOT_MET")

    lot["cert_status"] = "CERTIFIED"
    lot["certified_at"] = store.now()
    touch(lot)
    return ok(lot_out(lot))


@lots_bp.post("/toolworks/production-lots/<id>/rework")
def rework_lot(id):
    auth(*PLANNER)
    lot = lookup(store.lots, id, "ERR_PRODUCTION_LOT_NOT_FOUND")
    body = get_body()
    req_str(body, "rework_note")

    if lot["cert_status"] != "REJECTED":
        raise ApiError("ERR_LOT_CERT_STATE_INVALID")
    if lot["rework_cycle_count"] >= calc.REWORK_LIMIT:
        raise ApiError("ERR_REWORK_LIMIT_EXCEEDED")

    lot["cert_status"] = "DRAFT"
    lot["disposition"] = "IN_PROCESS"
    lot["process_status"] = "MACHINED"
    lot["hardness_index_sample"] = None
    lot["hardness_index_pooled"] = None
    lot["rework_cycle_count"] += 1
    touch(lot)
    return ok(lot_out(lot))


@lots_bp.post("/toolworks/production-lots/<id>/release")
def release_lot(id):
    auth(*PLANNER)
    lot = lookup(store.lots, id, "ERR_PRODUCTION_LOT_NOT_FOUND")
    body = get_body()
    expected_sku_version = req_int(body, "expected_sku_version")

    if lot["disposition"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED")
    if lot["disposition"] != "IN_PROCESS":
        raise ApiError("ERR_LOT_ALREADY_DISPOSITIONED")

    sku = store.skus[lot["sku_id"]]
    if expected_sku_version != sku["version"]:
        raise ApiError("ERR_STALE_SKU_VERSION")

    if lot["cert_status"] != "CERTIFIED":
        raise ApiError("ERR_LOT_NOT_CERTIFIED")

    lot["disposition"] = "RELEASED"
    sku["units_received_total"] += lot["unit_count"]
    svc.recompute_units(sku)
    touch(sku)
    touch(lot)
    return ok(lot_out(lot))


@lots_bp.get("/toolworks/production-lots/<id>/test-runs")
def lot_test_runs(id):
    auth("QualityEngineer", "ProductionPlanner", "PlatformAdmin")
    lookup(store.lots, id, "ERR_PRODUCTION_LOT_NOT_FOUND")
    rows = [r for r in store.runs.values() if r["lot_id"] == id]
    filters = {"test_type": filter_arg("test_type"), "status": filter_arg("status")}
    items, limit, offset, total = listing(rows, run_out, filters)
    return ok_list(items, limit, offset, total)
