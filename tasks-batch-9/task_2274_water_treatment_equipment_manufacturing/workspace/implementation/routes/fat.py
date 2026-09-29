"""Test bay booking and factory acceptance testing."""
from flask import Blueprint

import auth
import calc
import constants as C
import db
import domain
import response
import serialize
import validate
from errors import fail
from util import D, format_dt, whole_minutes

bp = Blueprint("fat", __name__)


@bp.post("/fat-runs")
def book_run():
    auth.require("FabricationManager")
    body = validate.body()
    skid = validate.catalog_ref(body, "skid_id", "skids")
    bay = validate.catalog_ref(body, "test_bay_id", "test_bays")
    validate.string(body, "skid_id")
    validate.string(body, "test_bay_id")
    start = validate.instant(body, "scheduled_start_at")
    end = validate.instant(body, "scheduled_end_at")
    expected_skid_version = validate.integer(body, "expected_skid_version", minimum=0)
    if end <= start:
        fail("ERR_INVALID_REQUEST",
             "scheduled_end_at must be strictly after scheduled_start_at")

    domain.check_version(skid, expected_skid_version, "ERR_STALE_SKID_VERSION")

    package = domain.package_of_skid(skid)
    if (package is None or package["status"] != "RELEASED_FOR_FAB"
            or skid["fat_readiness"] != "READY"):
        fail("ERR_SKID_NOT_FAT_READY", "the skid is not ready for factory testing")

    if bay["status"] != "AVAILABLE":
        fail("ERR_TEST_BAY_UNAVAILABLE", "the test bay is not available")

    overlap = calc.overlapping_runs(bay, start, end, exclude_skid_id=skid["id"])
    incoming_exclusive = bool(skid["requires_exclusive_bay"])
    if any(_run_requires_exclusive(run) for run in overlap):
        fail("ERR_TEST_BAY_EXCLUSIVE_CONFLICT",
             "an overlapping run requires exclusive use of the bay")
    if incoming_exclusive and overlap:
        fail("ERR_TEST_BAY_EXCLUSIVE_CONFLICT",
             "this skid requires exclusive use of the bay")

    footprint_sf = D(skid["footprint_sf"])
    occupied = sum((D(run["footprint_sf"]) for run in overlap), D(0))
    if occupied + footprint_sf > D(bay["max_skid_footprint_sf"]):
        fail("ERR_TEST_BAY_CAPACITY_EXCEEDED",
             "the bay cannot host the combined skid footprint")

    # Displace any outstanding booking for this skid before scoring the new row.
    for run in db.all_rows("fat_runs"):
        if run["skid_id"] == skid["id"] and run["status"] == "SCHEDULED":
            run["status"] = "SUPERSEDED"
            domain.release_run_reservation(run)
            db.touch(run)

    closed = sum(1 for run in db.all_rows("fat_runs")
                 if run["skid_id"] == skid["id"]
                 and run["status"] in C.FAT_RUN_CLOSED_STATUSES)
    duration_minutes = whole_minutes(start, end)

    row = db.new_row("fat_runs")
    row.update({
        "skid_id": skid["id"],
        "test_bay_id": bay["id"],
        "round_no": closed + 1,
        "scheduled_start_at": format_dt(start),
        "scheduled_end_at": format_dt(end),
        "footprint_sf": skid["footprint_sf"],
        "duration_minutes": duration_minutes,
        "status": "SCHEDULED",
        "punchlist_item_count": 0,
        "witnessed_by_user_id": None,
        "result_note": None,
    })
    db.insert("fat_runs", row)

    domain.reserve_bay(bay, calc.footprint_minutes(row["footprint_sf"],
                                                   duration_minutes))
    db.touch(skid)
    return response.created(serialize.row(row))


def _run_requires_exclusive(run):
    skid = db.get("skids", run["skid_id"])
    return bool(skid and skid["requires_exclusive_bay"])


@bp.get("/fat-runs")
def list_runs():
    auth.require(*auth.ROLES)
    skid_id = validate.string_filter("skid_id")
    bay_id = validate.string_filter("test_bay_id")
    status = validate.enum_filter("status", C.FAT_STATUSES)
    rows = db.all_rows("fat_runs")
    if skid_id:
        rows = [r for r in rows if r["skid_id"] == skid_id]
    if bay_id:
        rows = [r for r in rows if r["test_bay_id"] == bay_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows, [("scheduled_start_at", "asc"), ("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/fat-runs/<run_id>")
def get_run(run_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.fat_run(run_id)))


@bp.post("/fat-runs/<run_id>/witness-result")
def witness_result(run_id):
    actor = auth.require("QualityEngineer")
    run = domain.fat_run(run_id)
    body = validate.body()
    requested = validate.enum(body, "result", C.WITNESS_RESULTS)
    punchlist = validate.integer(body, "punchlist_item_count", minimum=0)
    note = validate.string(body, "result_note", required=False, default=None,
                           max_length=2000, allow_blank=True)

    if run["status"] != "SCHEDULED":
        fail("ERR_FAT_RUN_NOT_SCHEDULED", "only a SCHEDULED run may be witnessed")

    skid = db.get("skids", run["skid_id"])
    package = domain.package_of_skid(skid) if skid else None
    if package is not None:
        domain.forbid_same_user(actor, package["designed_by_user_id"],
                                "ERR_SOD_DESIGNER_IS_REVIEWER")
    if skid is None or skid["fat_readiness"] != "READY":
        fail("ERR_SKID_NOT_FAT_READY", "the skid is no longer FAT ready")

    recorded = calc.witnessed_result(requested, punchlist)
    run["status"] = recorded
    run["punchlist_item_count"] = punchlist
    run["witnessed_by_user_id"] = actor
    run["result_note"] = note
    domain.release_run_reservation(run)
    db.touch(run)

    project = domain.project_of_package(package) if package else None

    if recorded == "PASSED":
        if package is not None and package["status"] == "RELEASED_FOR_FAB":
            package["status"] = "FAT_PASSED"
            db.touch(package)
        if project is not None:
            pairs = calc.project_packages(project["id"])
            if pairs and all(p["status"] in ("FAT_PASSED", "SHIPPED")
                             for _s, p in pairs):
                if project["status"] == "IN_FABRICATION":
                    project["status"] = "COMMISSIONING"
                    domain.recompute_posture(project)
    elif recorded == "CONDITIONAL":
        if project is not None:
            domain.recompute_posture(project)
    else:
        if skid["mechanical_status"] == "MECH_COMPLETE":
            skid["mechanical_status"] = "REWORK"
        skid["rework_count"] = int(skid["rework_count"]) + 1
        if package is not None and package["status"] == "RELEASED_FOR_FAB":
            package["status"] = "REWORK_HOLD"
            db.touch(package)
        if package is not None:
            domain.refresh_skid_readiness(skid, package)
        db.touch(skid)
        if project is not None:
            domain.recompute_posture(project)

    return response.ok(serialize.row(run))


@bp.post("/fat-runs/<run_id>/cancel")
def cancel_run(run_id):
    auth.require("FabricationManager")
    run = domain.fat_run(run_id)
    body = validate.body()
    validate.string(body, "cancel_reason", required=False, default=None,
                    max_length=2000, allow_blank=True)

    if run["status"] != "SCHEDULED":
        fail("ERR_FAT_RUN_NOT_SCHEDULED", "only a SCHEDULED run may be cancelled")

    run["status"] = "CANCELLED"
    domain.release_run_reservation(run)
    db.touch(run)
    return response.ok(serialize.row(run))
