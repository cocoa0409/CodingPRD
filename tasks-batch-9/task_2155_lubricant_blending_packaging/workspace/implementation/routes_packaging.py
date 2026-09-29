"""Packaging runs."""
from flask import Blueprint

import calc
import cascades
import enums
import store
import views
from core import (authenticate, body, fail, pagination, q_enum, q_str, req_dt, req_int,
                  req_str, sec)

bp = Blueprint("packaging", __name__)


@bp.post("/packaging-runs")
def create_run():
    authenticate(["BlendOperator"])
    b = body()
    batch_id = req_str(b, "blend_batch_id")
    config_id = req_str(b, "package_configuration_id")
    line_id = req_str(b, "packaging_line_id")
    window_start = req_dt(b, "window_start")
    window_end = req_dt(b, "window_end")
    planned_units = req_int(b, "planned_units", gt=0)

    batch = store.must_get("BlendBatch", batch_id)                   # rung 5
    config = store.must_get("PackageConfiguration", config_id)
    line = store.must_get("PackagingLine", line_id)

    if batch["production_status"] != "RELEASED":                     # rung 14
        fail("ERR_BATCH_NOT_RELEASED")
    if config["status"] != "ACTIVE":                                 # rung 15
        fail("ERR_CONFIG_NOT_ACTIVE")
    if line["status"] != "AVAILABLE":                                # rung 16
        fail("ERR_LINE_NOT_AVAILABLE")
    if (config["claim_codes"] or []) and not batch["claim_eligible"]:  # rung 22
        fail("ERR_CLAIM_NOT_SUBSTANTIATED")

    overlapping = 0                                                  # rung 25
    for run in store.where("PackagingRun", packaging_line_id=line["id"]):
        if run["status"] not in ("SCHEDULED", "RUNNING"):
            continue
        if (sec(window_start) <= sec(run["window_end"])
                and sec(run["window_start"]) <= sec(window_end)):
            overlapping += 1
    if overlapping >= line["max_concurrent_runs"]:
        fail("ERR_LINE_CAPACITY_EXCEEDED")

    if not sec(window_end) > sec(window_start):                      # rung 26
        fail("ERR_INVALID_WINDOW")

    run = store.insert("PackagingRun", {
        "blend_batch_id": batch["id"],
        "package_configuration_id": config["id"],
        "packaging_line_id": line["id"],
        "window_start": window_start,
        "window_end": window_end,
        "planned_units": planned_units,
        "produced_units": None,
        "status": "SCHEDULED",
        "cancel_reason": None,
    })
    cascades.refresh_scheduled_run_count(line)
    return views.one(run, 201)


@bp.get("/packaging-runs/<rid>")
def read_run(rid):
    authenticate(views.STAFF_ALL)
    return views.one(store.must_get("PackagingRun", rid))


@bp.get("/packaging-runs")
def list_runs():
    authenticate(views.STAFF_ALL)
    limit, offset = pagination()
    batch_id = q_str("blend_batch_id")
    config_id = q_str("package_configuration_id")
    line_id = q_str("packaging_line_id")
    status = q_enum("status", enums.RUN_STATUSES)
    rows = store.where("PackagingRun", blend_batch_id=batch_id,
                       package_configuration_id=config_id,
                       packaging_line_id=line_id, status=status)
    return views.listing(views.by_created_asc(rows), limit, offset)


@bp.post("/packaging-runs/<rid>/start")
def start_run(rid):
    authenticate(["BlendOperator"])
    run = store.must_get("PackagingRun", rid)
    if run["status"] != "SCHEDULED":                                 # rung 10
        fail("ERR_INVALID_STATE")
    config = store.get("PackageConfiguration", run["package_configuration_id"])
    if config is None or config["status"] != "ACTIVE":               # rung 15
        fail("ERR_CONFIG_NOT_ACTIVE")
    line = store.get("PackagingLine", run["packaging_line_id"])
    if line is None or line["status"] != "AVAILABLE":                # rung 16
        fail("ERR_LINE_NOT_AVAILABLE")
    run["status"] = "RUNNING"
    store.touch(run)
    cascades.refresh_scheduled_run_count(line)
    return views.one(run)


@bp.post("/packaging-runs/<rid>/complete")
def complete_run(rid):
    authenticate(["BlendOperator"])
    b = body()
    produced_units = req_int(b, "produced_units", ge=0)
    run = store.must_get("PackagingRun", rid)
    if run["status"] != "RUNNING":
        fail("ERR_INVALID_STATE")
    run["status"] = "COMPLETED"
    run["produced_units"] = produced_units
    store.touch(run)
    line = store.get("PackagingLine", run["packaging_line_id"])
    if line is not None:
        cascades.refresh_scheduled_run_count(line)
    return views.one(run)


@bp.post("/packaging-runs/<rid>/cancel")
def cancel_run(rid):
    authenticate(["BlendOperator"])
    b = body()
    reason = req_str(b, "reason")
    run = store.must_get("PackagingRun", rid)
    if run["status"] not in ("SCHEDULED", "RUNNING"):
        fail("ERR_INVALID_STATE")
    run["status"] = "CANCELLED"
    run["cancel_reason"] = reason
    store.touch(run)
    line = store.get("PackagingLine", run["packaging_line_id"])
    if line is not None:
        cascades.refresh_scheduled_run_count(line)
    return views.one(run)
