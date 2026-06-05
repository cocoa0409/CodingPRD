"""DowntimeEvent routes (PRD §3.8, §4) — log, list, fetch, resolve.

Failure-class reason codes (MECHANICAL_FAILURE, ELECTRICAL_FAILURE) feed the
asset's MTBF (on open) and MTTR (on resolve).
"""
from flask import Blueprint, request

import db
import errors
import serialize
from middleware import authenticate, authorize, get_json_body
from helpers import require_enum, require_dt, opt_str, parse_pagination, paginate
from response import object_response, array_response
from services import calc, workflow

bp = Blueprint("downtime_events", __name__)

REASON_CODES = {"MECHANICAL_FAILURE", "ELECTRICAL_FAILURE", "OPERATOR_ERROR", "PLANNED_PM", "IDLE"}
FAILURE_CODES = {"MECHANICAL_FAILURE", "ELECTRICAL_FAILURE"}


@bp.post("/assets/<aid>/downtime-events")
def create_downtime(aid):
    _, role = authenticate()
    authorize(role, ["Technician", "MaintenanceManager"])
    body = get_json_body()
    with db.LOCK:
        asset = db.assets.get(aid)
        if asset is None:
            raise errors.not_found()
        reason_code = require_enum(body, "reason_code", REASON_CODES)
        started_at = require_dt(body, "started_at")
        work_order_id = opt_str(body, "work_order_id", default=None)
        if work_order_id is not None and work_order_id not in db.work_orders:
            raise errors.reference_not_found("work_order_id does not reference an existing work order.")

        # Overlap (priority 11): an asset cannot have two concurrently-open
        # downtimes. Any existing OPEN downtime on the asset is an open ray that
        # overlaps the new open ray.
        for d in db.downtime_events.values():
            if d["asset_id"] == aid and d["status"] == "OPEN":
                raise errors.ApiError(errors.ERR_DOWNTIME_OVERLAP,
                                      "The asset already has an open downtime event.", 409)

        rec = db.new_record()
        rec.update({
            "asset_id": aid,
            "work_order_id": work_order_id,
            "reason_code": reason_code,
            "started_at": db.iso(started_at),
            "ended_at": None,
            "status": "OPEN",
            "duration_hours": 0,
        })
        db.downtime_events[rec["id"]] = rec

        # Asset OPERATIONAL -> DOWN.
        workflow.refresh_asset_status_for_downtime(asset, opening=True)
        # MTBF recompute on failure-class open.
        if reason_code in FAILURE_CODES:
            calc.recompute_mtbf(asset)
        return object_response(serialize.downtime_event(rec), 201)


@bp.get("/assets/<aid>/downtime-events")
def list_asset_downtime(aid):
    _, role = authenticate()
    authorize(role, ["MaintenanceManager", "Planner", "Technician"])
    limit, offset = parse_pagination()
    with db.LOCK:
        if aid not in db.assets:
            raise errors.not_found()
        items = sorted(
            (d for d in db.downtime_events.values() if d["asset_id"] == aid),
            key=lambda d: d["_seq"])
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.downtime_event(d) for d in page],
                              limit, offset, total)


@bp.get("/downtime-events/<did>")
def get_downtime(did):
    _, role = authenticate()
    authorize(role, ["MaintenanceManager", "Planner", "Technician"])
    with db.LOCK:
        rec = db.downtime_events.get(did)
        if rec is None:
            raise errors.not_found()
        return object_response(serialize.downtime_event(rec), 200)


@bp.get("/downtime-events")
def list_downtime():
    _, role = authenticate()
    authorize(role, ["MaintenanceManager", "Planner", "Technician"])
    limit, offset = parse_pagination()
    work_order_id = request.args.get("work_order_id")
    with db.LOCK:
        items = sorted(db.downtime_events.values(), key=lambda d: d["_seq"])
        if work_order_id is not None:
            items = [d for d in items if d.get("work_order_id") == work_order_id]
        total = len(items)
        page = paginate(items, limit, offset)
        return array_response([serialize.downtime_event(d) for d in page],
                              limit, offset, total)


@bp.post("/downtime-events/<did>/resolve")
def resolve_downtime(did):
    _, role = authenticate()
    authorize(role, ["Technician", "MaintenanceManager"])
    body = get_json_body()
    with db.LOCK:
        rec = db.downtime_events.get(did)
        if rec is None:
            raise errors.not_found()
        ended_at = require_dt(body, "ended_at")
        if rec["status"] != "OPEN":
            raise errors.invalid_state("Downtime event is not OPEN.")
        started_at = db.parse_stored_dt(rec["started_at"])
        # Interval validity (priority 12): ended_at > started_at AND must not
        # extend past the started_at of the next FAILURE-class downtime on the
        # same asset (closed intervals may touch but not overlap).
        if not (ended_at > started_at):
            raise errors.ApiError(errors.ERR_DOWNTIME_INTERVAL_INVALID,
                                  "ended_at must be strictly after started_at.", 422)
        next_failure_start = None
        for d in db.downtime_events.values():
            if d["id"] == did:
                continue
            if d["asset_id"] != rec["asset_id"]:
                continue
            if d["reason_code"] not in FAILURE_CODES:
                continue
            d_start = db.parse_stored_dt(d["started_at"])
            if d_start > started_at:
                if next_failure_start is None or d_start < next_failure_start:
                    next_failure_start = d_start
        if next_failure_start is not None and ended_at > next_failure_start:
            raise errors.ApiError(errors.ERR_DOWNTIME_INTERVAL_INVALID,
                                  "Resolved interval overlaps the next failure-class downtime.", 422)

        rec["ended_at"] = db.iso(ended_at)
        rec["status"] = "RESOLVED"
        rec["duration_hours"] = (ended_at - started_at).total_seconds() / 3600.0
        db.touch(rec)

        asset = db.assets.get(rec["asset_id"])
        if rec["reason_code"] in FAILURE_CODES and asset is not None:
            calc.recompute_mttr(asset)
        # If this was the asset's last open downtime, DOWN -> OPERATIONAL.
        if asset is not None:
            workflow.refresh_asset_status_for_downtime(asset, opening=False)
        return object_response(serialize.downtime_event(rec), 200)
