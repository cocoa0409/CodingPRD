"""Production runs, QC disposition and batch stock (PRD 3.6, 3.7)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import calc
import cascades
from calc import d, rhu
from db import db, new_row, now, ordered, serialize as _ser, touch
from errors import ApiError
from middleware import authorize, find, user_id
from response import enum_filter, list_response, object_response, string_filter
from support import (STATUS_CREATED, body, film_available_check, license_active_check,
                     license_term_check, license_window_check, unique)
from validate import field as F
from validate import invalid, validate

bp = Blueprint("production", __name__)

RUN_STATUS = ("PLANNED", "SETUP", "RUNNING", "COMPLETED", "ABORTED")
QC_DISPOSITION = ("PENDING", "RELEASED", "QUARANTINED", "SCRAPPED")
BATCH_STATUS = ("IN_PRODUCTION", "IN_STOCK", "HELD", "SCRAPPED")
LINE_STATUS = ("ACTIVE", "VOIDED")

RUN_READERS = ("PlantAdmin", "ProductionPlanner", "QaTechnician", "TechnicalDirector")
BATCH_READERS = ("PlantAdmin", "ProductionPlanner", "QaTechnician", "WarrantyAdjuster",
                 "Distributor")

SETUP_LEAD_MINUTES = 120
SLIP_REQUALIFICATION_DAYS = 180
ZERO2 = Decimal("0.00")

RUN_CREATE = [
    F("run_code", "string", required=True),
    F("sku_id", "string", required=True),
    F("press_line_id", "string", required=True),
    F("planned_start_utc", "datetime", required=True),
    F("planned_end_utc", "datetime", required=True),
    F("planned_quantity_sqm", "number", required=True, exclusive_min=0, decimals=2),
]


def _active_runs(exclude_run_id=None):
    for run in db.production_runs.values():
        if run["run_status"] == "ABORTED":
            continue
        if exclude_run_id is not None and run["id"] == exclude_run_id:
            continue
        yield run


def _line_available(press_line):
    """Band 10 (V-XSTATE-3)."""
    if press_line["status"] != "AVAILABLE":
        raise ApiError("ERR_PRESS_LINE_UNAVAILABLE")


def _run_state_guard(run, allowed):
    if run["run_status"] not in allowed:
        raise ApiError("ERR_INVALID_RUN_STATE")


def _batch_of_run(run):
    for batch in ordered(list(db.batches.values())):
        if batch["production_run_id"] == run["id"]:
            return batch
    return None


# ---------------------------------------------------------------------------
# ProductionRun
# ---------------------------------------------------------------------------

@bp.post("/production-runs")
def create_run():
    authorize("ProductionPlanner")
    data = validate(RUN_CREATE, body())
    if data["planned_end_utc"] <= data["planned_start_utc"]:
        invalid()
    sku = find("product_skus", data["sku_id"])
    press_line = find("press_lines", data["press_line_id"])

    # band 10
    if (sku["certification_status"] not in ("TESTING", "PROVISIONAL", "CERTIFIED")
            or sku["commercial_status"] == "DISCONTINUED"):
        raise ApiError("ERR_SKU_NOT_PRODUCIBLE")
    _line_available(press_line)

    # band 12
    unique("production_runs", "run_code", data["run_code"])
    thickness = d(sku["overall_thickness_mm"])
    if thickness < d(press_line["min_thickness_mm"]) or thickness > d(press_line["max_thickness_mm"]):
        raise ApiError("ERR_THICKNESS_OUT_OF_LINE_RANGE")

    start = data["planned_start_utc"]
    end = data["planned_end_utc"]
    film = calc.film_of(sku)
    license_row = calc.license_of_film(film)

    # band 13 -- V-TEMP-1 half-open line occupation
    for other in _active_runs():
        if other["press_line_id"] != press_line["id"]:
            continue
        if start < other["planned_end_utc"] and other["planned_start_utc"] < end:
            raise ApiError("ERR_PRESS_LINE_WINDOW_CONFLICT")

    # band 13 -- V-TEMP-2 changeover buffer
    predecessor = calc.predecessor_run(press_line["id"], start)
    required_gap = calc.changeover_gap_minutes(press_line, sku, predecessor)
    if predecessor is not None:
        gap_seconds = (start - predecessor["planned_end_utc"]).total_seconds()
        if gap_seconds < required_gap * 60:
            raise ApiError("ERR_CHANGEOVER_GAP_INSUFFICIENT")

    # band 13 -- V-TEMP-3 closed-interval roll-set capacity
    if film is not None:
        overlapping = 0
        for other in _active_runs():
            other_sku = db.product_skus.get(other["sku_id"])
            if other_sku is None or other_sku["print_film_id"] != film["id"]:
                continue
            if start <= other["planned_end_utc"] and other["planned_start_utc"] <= end:
                overlapping += 1
        if overlapping >= film["master_roll_sets"]:
            raise ApiError("ERR_PRINT_FILM_ROLL_CAPACITY_EXCEEDED")

    # band 13 -- V-TEMP-4 licensed term.  The lazy EXPIRED flip is driven by the
    # logical clock; the planned window is then read against the same term but
    # never rewrites the grant's status (PRD 3.2).
    if license_row is not None:
        license_term_check(license_row, now())
        license_window_check(license_row, start)

    # band 14
    film_available_check(film)
    license_active_check(license_row)

    # band 15 -- V-FISC-1 term volume cap
    projected = rhu(d(license_row["consumed_volume_sqm"])
                    + d(license_row["reserved_volume_sqm"])
                    + data["planned_quantity_sqm"], 2)
    if projected > d(license_row["term_volume_cap_sqm"]):
        raise ApiError("ERR_LICENSE_VOLUME_CAP_EXCEEDED")

    row = new_row()
    row.update({
        "run_code": data["run_code"],
        "sku_id": sku["id"],
        "press_line_id": press_line["id"],
        "planned_start_utc": start,
        "planned_end_utc": end,
        "planned_quantity_sqm": data["planned_quantity_sqm"],
        "run_status": "PLANNED",
        "qc_disposition": "PENDING",
        "changeover_minutes_applied": None,
        "actual_quantity_sqm": ZERO2,
        "registration_drift_mm": None,
        "curl_deviation_mm": None,
        "emboss_alignment_offset_mm": None,
        "measured_tongue_thickness_mm": None,
        "wear_layer_measured_mil": None,
        "pattern_waste_sqm": None,
        "registration_within_tolerance": None,
        "emboss_within_tolerance": None,
        "curl_within_tolerance": None,
        "tongue_within_tolerance": None,
        "auto_disposition_recommendation": None,
        "royalty_accrued_cents": 0,
        "completed_by_user_id": None,
        "abort_reason": None,
    })
    db.production_runs[row["id"]] = row

    license_row["reserved_volume_sqm"] = rhu(
        d(license_row["reserved_volume_sqm"]) + data["planned_quantity_sqm"], 2)
    touch(license_row)
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/production-runs")
def list_runs():
    authorize(*RUN_READERS)
    run_status = enum_filter(request.args, "run_status", RUN_STATUS)
    qc = enum_filter(request.args, "qc_disposition", QC_DISPOSITION)
    sku_id = string_filter(request.args, "sku_id")
    line_id = string_filter(request.args, "press_line_id")
    rows = [r for r in db.production_runs.values()
            if (run_status is None or r["run_status"] == run_status)
            and (qc is None or r["qc_disposition"] == qc)
            and (sku_id is None or r["sku_id"] == sku_id)
            and (line_id is None or r["press_line_id"] == line_id)]
    return list_response(rows, request.args, _ser)


@bp.get("/production-runs/<row_id>")
def read_run(row_id):
    authorize(*RUN_READERS)
    return object_response(_ser(find("production_runs", row_id)))


@bp.post("/production-runs/<row_id>/setup")
def setup_run(row_id):
    authorize("ProductionPlanner")
    run = find("production_runs", row_id)
    _run_state_guard(run, ("PLANNED",))
    sku = db.product_skus.get(run["sku_id"])
    press_line = db.press_lines.get(run["press_line_id"])
    if (sku["certification_status"] not in ("PROVISIONAL", "CERTIFIED")
            or sku["commercial_status"] not in ("DEVELOPMENT", "RELEASED")):
        raise ApiError("ERR_SKU_NOT_PRODUCIBLE")
    _line_available(press_line)
    if now() < run["planned_start_utc"] - timedelta(minutes=SETUP_LEAD_MINUTES):
        raise ApiError("ERR_SETUP_TOO_EARLY")

    predecessor = calc.predecessor_run(press_line["id"], run["planned_start_utc"],
                                       exclude_run_id=run["id"])
    run["changeover_minutes_applied"] = calc.changeover_gap_minutes(press_line, sku, predecessor)
    run["run_status"] = "SETUP"
    touch(run)
    return object_response(_ser(run))


def _slip_qualified(sku):
    horizon = now() - timedelta(days=SLIP_REQUALIFICATION_DAYS)
    for panel in db.test_panels.values():
        if panel["sku_id"] != sku["id"] or panel["status"] != "PASSED":
            continue
        if panel["updated_at"] <= horizon:
            continue
        for result in db.test_results.values():
            if (result["test_panel_id"] == panel["id"]
                    and result["attempt_no"] == panel["attempt_no"]
                    and result["test_type"] == "SLIP_RESISTANCE"
                    and result["outcome"] == "PASS"):
                return True
    return False


@bp.post("/production-runs/<row_id>/start")
def start_run(row_id):
    authorize("ProductionPlanner")
    run = find("production_runs", row_id)
    _run_state_guard(run, ("SETUP",))
    sku = db.product_skus.get(run["sku_id"])
    press_line = db.press_lines.get(run["press_line_id"])
    _line_available(press_line)
    if sku["waterproof_rated"] and not _slip_qualified(sku):
        raise ApiError("ERR_SLIP_RESISTANCE_NOT_QUALIFIED")

    film = calc.film_of(sku)
    license_row = calc.license_of_film(film)
    if license_row is not None:
        license_term_check(license_row, now())
    film_available_check(film)
    license_active_check(license_row)

    run["run_status"] = "RUNNING"
    touch(run)
    return object_response(_ser(run))


RUN_COMPLETE = [
    F("actual_quantity_sqm", "number", required=True, min=0, decimals=2),
    F("registration_drift_mm", "number", required=True),
    F("curl_deviation_mm", "number", required=True),
    F("emboss_alignment_offset_mm", "number", required=True),
    F("wear_layer_measured_mil", "number", required=True),
    F("measured_tongue_thickness_mm", "number"),
]


@bp.post("/production-runs/<row_id>/complete")
def complete_run(row_id):
    authorize("ProductionPlanner")
    data = validate(RUN_COMPLETE, body())
    run = find("production_runs", row_id)
    _run_state_guard(run, ("RUNNING",))

    sku = db.product_skus.get(run["sku_id"])
    film = calc.film_of(sku)
    license_row = calc.license_of_film(film)
    press_line = db.press_lines.get(run["press_line_id"])

    run.update({
        "actual_quantity_sqm": data["actual_quantity_sqm"],
        "registration_drift_mm": data["registration_drift_mm"],
        "curl_deviation_mm": data["curl_deviation_mm"],
        "emboss_alignment_offset_mm": data["emboss_alignment_offset_mm"],
        "wear_layer_measured_mil": data["wear_layer_measured_mil"],
        "measured_tongue_thickness_mm": data["measured_tongue_thickness_mm"],
    })
    run.update(calc.run_quality_metrics(run, sku, film, press_line))
    run["run_status"] = "COMPLETED"
    run["completed_by_user_id"] = user_id()

    if license_row is not None:
        license_row["reserved_volume_sqm"] = rhu(
            d(license_row["reserved_volume_sqm"]) - d(run["planned_quantity_sqm"]), 2)
        license_row["consumed_volume_sqm"] = rhu(
            d(license_row["consumed_volume_sqm"]) + d(run["actual_quantity_sqm"]), 2)
        royalty = calc.run_royalty_cents(run, sku, license_row)
        run["royalty_accrued_cents"] = royalty
        license_row["accrued_royalty_cents"] = license_row["accrued_royalty_cents"] + royalty
        touch(license_row)
    touch(run)

    if d(run["actual_quantity_sqm"]) > 0:
        _mint_batch(run, sku, film, license_row, press_line)
    return object_response(_ser(run))


def _mint_batch(run, sku, film, license_row, press_line):
    formulation = db.formulations.get(sku["formulation_id"])
    batch = new_row()
    batch.update({
        "batch_code": "%s-B1" % run["run_code"],
        "production_run_id": run["id"],
        "sku_id": sku["id"],
        "quantity_sqm": run["actual_quantity_sqm"],
        "available_quantity_sqm": ZERO2,
        "wear_layer_measured_mil": run["wear_layer_measured_mil"],
        "status": "IN_PRODUCTION",
        "hold_reason": None,
        "held_by_user_id": None,
        "traceability_snapshot": {
            "formulation_code": formulation["formulation_code"] if formulation else None,
            "formulation_revision": formulation["revision"] if formulation else None,
            "blended_cost_per_kg_cents": (formulation["blended_cost_per_kg_cents"]
                                          if formulation else None),
            "print_film_design_code": film["design_code"] if film else None,
            "license_code": license_row["license_code"] if license_row else None,
            "press_line_code": press_line["line_code"] if press_line else None,
            "planned_start_utc": run["planned_start_utc"],
            "planned_end_utc": run["planned_end_utc"],
            "wear_layer_mil_spec": sku["wear_layer_mil"],
        },
    })
    db.batches[batch["id"]] = batch
    return batch


@bp.post("/production-runs/<row_id>/abort")
def abort_run(row_id):
    authorize("ProductionPlanner")
    data = validate([F("abort_reason", "string", required=True)], body())
    run = find("production_runs", row_id)
    _run_state_guard(run, ("PLANNED", "SETUP", "RUNNING"))
    cascades.abort_run(run, data["abort_reason"])
    return object_response(_ser(run))


QC_FROM = {
    "RELEASED": ("PENDING", "QUARANTINED"),
    "QUARANTINED": ("PENDING",),
    "SCRAPPED": ("PENDING", "QUARANTINED", "RELEASED"),
}


@bp.post("/production-runs/<row_id>/qc-disposition")
def qc_disposition(row_id):
    authorize("QaTechnician")
    data = validate([
        F("to_disposition", "string", required=True, enum=QC_DISPOSITION),
        F("hold_reason", "string"),
    ], body())
    to_disposition = data["to_disposition"]
    run = find("production_runs", row_id)
    if run["run_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_QC_TRANSITION")
    if run["qc_disposition"] not in QC_FROM.get(to_disposition, ()):
        raise ApiError("ERR_INVALID_QC_TRANSITION")
    if to_disposition == "RELEASED":
        gates = ("registration_within_tolerance", "emboss_within_tolerance",
                 "curl_within_tolerance", "tongue_within_tolerance")
        if any(run.get(gate) is False for gate in gates):
            raise ApiError("ERR_QC_GATES_NOT_MET")

    batch = _batch_of_run(run)
    run["qc_disposition"] = to_disposition
    touch(run)

    if to_disposition == "RELEASED":
        if batch is not None and batch["status"] in ("IN_PRODUCTION", "HELD"):
            batch["status"] = "IN_STOCK"
            batch["available_quantity_sqm"] = rhu(d(batch["quantity_sqm"]), 2)
            batch["hold_reason"] = None
            batch["held_by_user_id"] = None
            touch(batch)
    elif to_disposition == "QUARANTINED":
        if batch is not None and batch["status"] == "IN_PRODUCTION":
            batch["status"] = "HELD"
            batch["hold_reason"] = "QC_QUARANTINE"
            batch["held_by_user_id"] = user_id()
            touch(batch)
    else:
        license_row = calc.license_of_run(run)
        if license_row is not None:
            license_row["consumed_volume_sqm"] = rhu(
                d(license_row["consumed_volume_sqm"]) - d(run["actual_quantity_sqm"]), 2)
            license_row["accrued_royalty_cents"] = (license_row["accrued_royalty_cents"]
                                                    - run["royalty_accrued_cents"])
            touch(license_row)
        run["royalty_accrued_cents"] = 0
        if batch is not None and batch["status"] != "SCRAPPED":
            cascades.scrap_batch(batch)
    return object_response(_ser(run))


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------

@bp.get("/batches")
def list_batches():
    authorize(*BATCH_READERS)
    status = enum_filter(request.args, "status", BATCH_STATUS)
    sku_id = string_filter(request.args, "sku_id")
    run_id = string_filter(request.args, "production_run_id")
    rows = [r for r in db.batches.values()
            if (status is None or r["status"] == status)
            and (sku_id is None or r["sku_id"] == sku_id)
            and (run_id is None or r["production_run_id"] == run_id)]
    return list_response(rows, request.args, _ser)


@bp.get("/batches/<row_id>")
def read_batch(row_id):
    authorize(*BATCH_READERS)
    return object_response(_ser(find("batches", row_id)))


@bp.get("/batches/<row_id>/allocation-lines")
def batch_lines(row_id):
    authorize("PlantAdmin", "ProductionPlanner", "QaTechnician", "Distributor")
    batch = find("batches", row_id)
    status = enum_filter(request.args, "status", LINE_STATUS)
    rows = [line for line in db.allocation_lines.values()
            if line["batch_id"] == batch["id"]
            and (status is None or line["status"] == status)]
    return list_response(rows, request.args, _ser)


BATCH_ACTION_FROM = {
    "HOLD": ("IN_STOCK",),
    "RELEASE_HOLD": ("HELD",),
    "SCRAP": ("IN_PRODUCTION", "IN_STOCK", "HELD"),
}


@bp.post("/batches/<row_id>/hold-status")
def batch_hold_status(row_id):
    authorize("QaTechnician")
    data = validate([
        F("action", "string", required=True, enum=("HOLD", "RELEASE_HOLD", "SCRAP")),
        F("hold_reason", "string"),
    ], body())
    action = data["action"]
    batch = find("batches", row_id)
    if batch["status"] not in BATCH_ACTION_FROM[action]:
        raise ApiError("ERR_INVALID_BATCH_STATE")

    if action == "RELEASE_HOLD":
        if user_id() == batch["held_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        run = db.production_runs.get(batch["production_run_id"])
        if run is None or run["qc_disposition"] != "RELEASED":
            raise ApiError("ERR_RUN_NOT_RELEASED")
        sku = db.product_skus.get(batch["sku_id"])
        if (sku is None or sku["commercial_status"] == "DISCONTINUED"
                or sku["certification_status"] in ("SUSPENDED", "DECERTIFIED")):
            raise ApiError("ERR_SKU_NOT_PRODUCIBLE")
        drawn = sum((d(line["quantity_sqm"])
                     for line in cascades.active_lines_of_batch(batch)), Decimal(0))
        batch["status"] = "IN_STOCK"
        batch["hold_reason"] = None
        batch["held_by_user_id"] = None
        batch["available_quantity_sqm"] = rhu(d(batch["quantity_sqm"]) - drawn, 2)
        touch(batch)
    elif action == "HOLD":
        cascades.hold_batch(batch, data["hold_reason"], user_id(), void_lines=True)
    else:
        if data["hold_reason"] is not None:
            batch["hold_reason"] = data["hold_reason"]
        cascades.scrap_batch(batch)
    return object_response(_ser(batch))


__all__ = ["bp"]
