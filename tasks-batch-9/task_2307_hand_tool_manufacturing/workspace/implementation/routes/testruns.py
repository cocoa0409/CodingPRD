"""TestRun endpoints (PRD §3.3, §3.4)."""

from flask import Blueprint

import calculations as calc
import services as svc
from errors import ApiError
from envelope import ok, ok_list
from routes.helpers import listing
from serialize import run_out
from store import base_row, store, touch, with_common
from validate import (auth, bool_filter_arg, filter_arg, get_body, lookup, req_enum, req_int,
                     req_number_array, req_str, require_present, resolve_ref, window_fields)

runs_bp = Blueprint("runs", __name__)

QE = ["QualityEngineer", "PlatformAdmin"]
STAGE_ORDER = calc.PROCESS_STATUSES


def _stage_reached(lot, required_stage):
    return STAGE_ORDER.index(lot["process_status"]) >= STAGE_ORDER.index(required_stage)


def _chamber_peak_load(chamber_id, start, end, specimen_count):
    blocking = []
    for run in svc.sorted_rows([r for r in store.runs.values()
                                if r["chamber_id"] == chamber_id]):
        if run["status"] not in ("SCHEDULED", "PASSED", "FAILED"):
            continue
        if run["window_start"] < end and start < run["window_end"]:
            blocking.append(run)

    probes = [start] + [r["window_start"] for r in blocking if r["window_start"] > start]
    peak = specimen_count
    for instant in probes:
        load = specimen_count
        for run in blocking:
            if run["window_start"] <= instant < run["window_end"]:
                load += run["specimen_count"]
        peak = max(peak, load)
    return peak


@runs_bp.post("/toolworks/test-runs")
def create_run():
    auth(*QE)
    body = get_body()

    chamber_supplied = "chamber_id" in body and body.get("chamber_id") is not None
    chamber = resolve_ref(body, "chamber_id", store.chambers, "ERR_CHAMBER_NOT_FOUND")
    lot = resolve_ref(body, "lot_id", store.lots, "ERR_PRODUCTION_LOT_NOT_FOUND")

    require_present(lot, "lot_id")
    test_type = req_enum(body, "test_type", calc.TEST_TYPES)
    specimen_count = req_int(body, "specimen_count", 1)
    start, end, raw_start, raw_end = window_fields(body)

    if test_type == "SALT_SPRAY":
        if chamber is None:
            raise ApiError("ERR_CHAMBER_REQUIRED")
    elif chamber_supplied:
        raise ApiError("ERR_CHAMBER_NOT_APPLICABLE")

    if lot["cert_status"] not in ("DRAFT", "IN_TEST"):
        raise ApiError("ERR_LOT_CERT_STATE_INVALID")
    if lot["disposition"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED")

    required_stage = calc.TEST_STAGE_REQUIREMENT[test_type]
    if required_stage is not None and not _stage_reached(lot, required_stage):
        raise ApiError("ERR_TEST_STAGE_TOO_EARLY")

    if test_type in calc.HEAT_TREAT_DEPENDENT_TESTS:
        completed_ends = [c["window_end"] for c in svc.lot_campaigns(lot["id"])
                          if c["status"] == "COMPLETED"]
        if completed_ends and start < min(completed_ends):
            raise ApiError("ERR_TEST_WINDOW_BEFORE_HEAT_TREAT")

    if specimen_count > lot["specimens_available"]:
        raise ApiError("ERR_SPECIMENS_EXHAUSTED")

    if test_type == "SALT_SPRAY":
        peak = _chamber_peak_load(chamber["id"], start, end, specimen_count)
        if peak > chamber["coupon_capacity"]:
            raise ApiError("ERR_CHAMBER_CAPACITY_EXCEEDED")

    sku = store.skus[lot["sku_id"]]
    row = with_common(base_row(
        lot_id=lot["id"],
        chamber_id=chamber["id"] if chamber is not None else None,
        test_type=test_type,
        specimen_count=specimen_count,
        window_start=start,
        window_end=end,
        window_start_raw=raw_start,
        window_end_raw=raw_end,
        mandatory=test_type in calc.MANDATORY_TESTS[sku["tool_family"]],
        readings=None,
        mean_reading=None,
        governing_statistic=None,
        requirement_value=calc.requirement_for(test_type, lot, sku),
        result_margin_pct=None,
        status="SCHEDULED",
        void_reason=None,
    ))
    store.runs[row["id"]] = row

    svc.recompute_specimens(lot)
    touch(lot)
    if lot["cert_status"] == "DRAFT":
        lot["cert_status"] = "IN_TEST"
        touch(lot)

    return ok(run_out(row), 201)


@runs_bp.get("/toolworks/test-runs")
def list_runs():
    auth("QualityEngineer", "ProductionPlanner", "PlatformAdmin")
    filters = {
        "chamber_id": filter_arg("chamber_id"),
        "test_type": filter_arg("test_type"),
        "status": filter_arg("status"),
    }
    mandatory = bool_filter_arg("mandatory")
    if mandatory is not None:
        filters["mandatory"] = mandatory
    items, limit, offset, total = listing(list(store.runs.values()), run_out, filters)
    return ok_list(items, limit, offset, total)


@runs_bp.get("/toolworks/test-runs/<id>")
def get_run(id):
    auth("QualityEngineer", "ProductionPlanner", "PlatformAdmin")
    row = lookup(store.runs, id, "ERR_TEST_RUN_NOT_FOUND")
    return ok(run_out(row))


@runs_bp.post("/toolworks/test-runs/<id>/results")
def submit_results(id):
    auth(*QE)
    run = lookup(store.runs, id, "ERR_TEST_RUN_NOT_FOUND")
    body = get_body()
    readings = req_number_array(body, "readings")
    if len(readings) != run["specimen_count"]:
        raise ApiError("ERR_READING_COUNT_MISMATCH")

    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_TEST_RUN_STATE_INVALID")

    outcome = calc.test_run_outcome(run["test_type"], readings, run["requirement_value"])
    run["readings"] = list(readings)
    run["mean_reading"] = outcome["mean_reading"]
    run["governing_statistic"] = outcome["governing_statistic"]
    run["requirement_value"] = outcome["requirement_value"]
    run["result_margin_pct"] = outcome["result_margin_pct"]
    run["status"] = outcome["status"]
    touch(run)

    lot = store.lots[run["lot_id"]]
    svc.recompute_specimens(lot)
    if run["status"] == "PASSED" and run["test_type"] == "HARDNESS":
        svc.recompute_hardness(lot)
    touch(lot)

    if run["status"] == "FAILED" and run["mandatory"] and lot["cert_status"] == "IN_TEST":
        svc.cascade_lot_rejection(lot)

    return ok(run_out(run))


@runs_bp.post("/toolworks/test-runs/<id>/void")
def void_run(id):
    auth(*QE)
    run = lookup(store.runs, id, "ERR_TEST_RUN_NOT_FOUND")
    body = get_body()
    void_reason = req_str(body, "void_reason")

    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_TEST_RUN_STATE_INVALID")

    run["status"] = "VOID"
    run["void_reason"] = void_reason
    touch(run)

    lot = store.lots[run["lot_id"]]
    svc.recompute_specimens(lot)
    touch(lot)
    return ok(run_out(run))
