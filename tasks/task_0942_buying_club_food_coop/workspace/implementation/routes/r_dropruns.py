"""Drop runs: creation, listing, merge and roll-forward (5 endpoints)."""

from flask import Blueprint

from core import clock, serialize
from core.constants import DROP_RUN_STATUSES, ROLES, ROLLFORWARD_MAX_PER_DROP_RUN
from core.envelope import created, ok, page
from core.errors import ApiError
from core.ladder import (body_fk, endpoint, enum_filter, free_filter, gate_coordinator,
                         gate_cycle_closed, pagination, path_row, req_id, req_int,
                         rung_drop_coordinator, rung_occ)
from core.store import DB
from services import droprun_ops

bp = Blueprint("dropruns", __name__)
R5 = list(ROLES)


@bp.post("/drop-runs")
@endpoint(["ClubAdmin", "DropCoordinator"])
def create_drop_run(ctx):
    cycle = body_fk(ctx, "cycle_id")                       # rung 5
    drop_point = body_fk(ctx, "drop_point_id")
    req_id(ctx, "cycle_id")                                # rung 7
    req_id(ctx, "drop_point_id")
    gate_cycle_closed(cycle)                               # rung 9
    gate_coordinator(ctx)                                  # rung 11
    row = droprun_ops.create_drop_run(cycle, drop_point)   # rung 37 inside
    return created(serialize.drop_run(row))


@bp.get("/drop-runs")
@endpoint(R5)
def list_drop_runs(ctx):
    limit, offset = pagination(ctx)
    status = enum_filter(ctx, "status", DROP_RUN_STATUSES)
    filters = {
        "cycle_id": free_filter(ctx, "cycle_id"),
        "drop_point_id": free_filter(ctx, "drop_point_id"),
        "route_run_id": free_filter(ctx, "route_run_id"),
        "coordinator_member_id": free_filter(ctx, "coordinator_member_id"),
        "merged_into_drop_run_id": free_filter(ctx, "merged_into_drop_run_id"),
    }
    rows = []
    for row in DB.all("DropRun"):
        if status is not None and row["status"] != status:
            continue
        if any(v is not None and row[k] != v for k, v in filters.items()):
            continue
        rows.append(row)
    return page(serialize.project_all(rows), limit, offset)


@bp.get("/drop-runs/<drop_run_id>")
@endpoint(R5)
def read_drop_run(ctx, drop_run_id):
    return ok(serialize.drop_run(path_row("drop_run_id", drop_run_id)))


@bp.post("/drop-runs/<drop_run_id>/merge")
@endpoint(["ClubAdmin", "DropCoordinator"])
def merge_drop_run(ctx, drop_run_id):
    source = path_row("drop_run_id", drop_run_id)          # rung 4
    target = body_fk(ctx, "target_drop_run_id")            # rung 5
    req_id(ctx, "target_drop_run_id")                      # rung 7
    req_int(ctx, "expected_drop_run_version")
    gate_cycle_closed(source)                              # rung 9
    gate_coordinator(ctx)                                  # rung 11
    if source["status"] != "OPEN":                         # rung 18
        raise ApiError("ERR_INVALID_DROP_RUN_STATE")
    cycle = DB.get("Cycle", source["cycle_id"])
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_INVALID_CYCLE_STATE")
    rung_occ(ctx, "expected_drop_run_version", source)     # rung 25
    rung_drop_coordinator(ctx, source)                     # rung 27
    if (target["id"] == source["id"]                       # rung 40
            or target["route_run_id"] != source["route_run_id"]
            or target["status"] != "OPEN"):
        raise ApiError("ERR_MERGE_TARGET_INVALID")
    droprun_ops.merge(source, target)
    return ok(serialize.drop_run(source))


@bp.post("/drop-runs/<drop_run_id>/roll-forward")
@endpoint(["ClubAdmin", "DropCoordinator"])
def roll_forward_drop_run(ctx, drop_run_id):
    source = path_row("drop_run_id", drop_run_id)          # rung 4
    target_cycle = body_fk(ctx, "target_cycle_id")         # rung 5
    req_id(ctx, "target_cycle_id")                         # rung 7
    gate_cycle_closed(source)                              # rung 9
    gate_coordinator(ctx)                                  # rung 11
    if source["status"] != "DEFERRED":                     # rung 18
        raise ApiError("ERR_INVALID_DROP_RUN_STATE")
    rung_drop_coordinator(ctx, source)                     # rung 27
    source_cycle = DB.get("Cycle", source["cycle_id"])     # rung 41
    if (source["rollforward_count"] >= ROLLFORWARD_MAX_PER_DROP_RUN
            or target_cycle["status"] != "OPEN"
            or clock.parse(target_cycle["cutoff_at"]) <= clock.parse(source_cycle["cutoff_at"])):
        raise ApiError("ERR_ROLLFORWARD_LIMIT")
    droprun_ops.roll_forward(source, target_cycle)
    return ok(serialize.drop_run(source))
