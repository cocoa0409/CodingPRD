"""Prefinishing: window loading, coating and posture holds (PRD 3.8)."""

from datetime import timedelta

from flask import Blueprint

from db import db, insert, ordered, touch
from errors import ApiError
from middleware import ALL_ROLES, MILL_ADMIN, PREFINISH_SCHEDULER, authorize
from response import array_response, object_response, paginate
from serializers import serialize, serialize_many
from services import calc, lookup
from validation import (body_json, opt_str, pagination, query_enum, query_str,
                        req_datetime, req_int, req_ref, req_str)

bp = Blueprint("prefinish", __name__)

RUN_STATUSES = ("SCHEDULED", "HELD", "RUNNING", "COMPLETED")
MAX_WINDOW = timedelta(hours=calc.MAX_PREFINISH_WINDOW_HOURS)


@bp.post("/mill/prefinish-runs")
@authorize(PREFINISH_SCHEDULER, MILL_ADMIN)
def create_prefinish_run():
    body = body_json()
    prefinish_line_id = req_ref(body, "prefinish_line_id")
    flooring_lot_id = req_ref(body, "flooring_lot_id")
    window_start_utc = req_datetime(body, "window_start_utc")
    window_end_utc = req_datetime(body, "window_end_utc")
    scheduled_linear_feet = req_int(body, "scheduled_linear_feet")
    sanding_grit_sequence = req_str(body, "sanding_grit_sequence")
    stain_code = opt_str(body, "stain_code")

    line = lookup.prefinish_line(prefinish_line_id)
    lot = lookup.flooring_lot(flooring_lot_id)
    product_line = db.product_lines[lot["product_line_id"]]

    if product_line["posture"] != "OPEN":
        raise ApiError("ERR_PRODUCT_LINE_POSTURE_BLOCKED")
    if lot["status"] != "GRADED":
        raise ApiError("ERR_LOT_NOT_GRADED")

    if window_end_utc <= window_start_utc or (window_end_utc - window_start_utc) > MAX_WINDOW:
        raise ApiError("ERR_PREFINISH_WINDOW_INVALID")

    loaded = 0
    for run in ordered(db.prefinish_runs):
        if run["prefinish_line_id"] != line["id"]:
            continue
        if run["status"] not in calc.PREFINISH_LOADING_STATUSES:
            continue
        if calc.prefinish_windows_overlap(run["window_start_utc"], run["window_end_utc"],
                                          window_start_utc, window_end_utc):
            loaded += int(run["scheduled_linear_feet"])
    if loaded + scheduled_linear_feet > int(line["daily_capacity_linear_feet"]):
        raise ApiError("ERR_PREFINISH_CAPACITY_EXCEEDED")

    record = insert(db.prefinish_runs, {
        "prefinish_line_id": prefinish_line_id,
        "flooring_lot_id": flooring_lot_id,
        "product_line_id": product_line["id"],
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "scheduled_linear_feet": scheduled_linear_feet,
        "sanding_grit_sequence": sanding_grit_sequence,
        "stain_code": stain_code,
        "coating_liters": calc.coating_liters(scheduled_linear_feet,
                                              lot["actual_milled_width_in"],
                                              line["coating_passes"]),
        "hold_reason": None,
        "status": "SCHEDULED",
    })
    return object_response(serialize("prefinish_run", record), 201)


@bp.get("/mill/prefinish-runs/<prefinish_run_id>")
@authorize(*ALL_ROLES)
def get_prefinish_run(prefinish_run_id):
    return object_response(serialize("prefinish_run", lookup.prefinish_run(prefinish_run_id)))


@bp.get("/mill/prefinish-runs")
@authorize(*ALL_ROLES)
def list_prefinish_runs():
    limit, offset = pagination()
    rows = lookup.filtered(db.prefinish_runs, [
        ("prefinish_line_id", query_str("prefinish_line_id")),
        ("flooring_lot_id", query_str("flooring_lot_id")),
        ("product_line_id", query_str("product_line_id")),
        ("status", query_enum("status", RUN_STATUSES)),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("prefinish_run", page), limit, offset, total)


@bp.post("/mill/prefinish-runs/<prefinish_run_id>/release_hold")
@authorize(PREFINISH_SCHEDULER, MILL_ADMIN)
def release_hold(prefinish_run_id):
    body_json()
    run = lookup.prefinish_run(prefinish_run_id)
    if run["status"] != "HELD":
        raise ApiError("ERR_PREFINISH_RUN_STATE_INVALID")
    line = db.product_lines[run["product_line_id"]]
    if line["posture"] != "OPEN":
        raise ApiError("ERR_PRODUCT_LINE_POSTURE_BLOCKED")
    run["status"] = "SCHEDULED"
    run["hold_reason"] = None
    touch(run)
    return object_response(serialize("prefinish_run", run))


@bp.post("/mill/prefinish-runs/<prefinish_run_id>/start")
@authorize(PREFINISH_SCHEDULER)
def start_prefinish_run(prefinish_run_id):
    body_json()
    run = lookup.prefinish_run(prefinish_run_id)
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_PREFINISH_RUN_STATE_INVALID")
    line = db.product_lines[run["product_line_id"]]
    if line["posture"] != "OPEN":
        raise ApiError("ERR_PRODUCT_LINE_POSTURE_BLOCKED")
    lot = db.flooring_lots[run["flooring_lot_id"]]
    if lot["status"] != "GRADED":
        raise ApiError("ERR_LOT_NOT_GRADED")
    run["status"] = "RUNNING"
    touch(run)
    return object_response(serialize("prefinish_run", run))


@bp.post("/mill/prefinish-runs/<prefinish_run_id>/complete")
@authorize(PREFINISH_SCHEDULER)
def complete_prefinish_run(prefinish_run_id):
    body_json()
    run = lookup.prefinish_run(prefinish_run_id)
    if run["status"] != "RUNNING":
        raise ApiError("ERR_PREFINISH_RUN_STATE_INVALID")
    run["status"] = "COMPLETED"
    touch(run)
    return object_response(serialize("prefinish_run", run))
