"""OpsSnapshot endpoints: run checkpoint, list/get, finalize SLA verdict."""
from flask import Blueprint, request

from db import db, stamp_new, touch
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE_TRANSITION
from middleware import require_roles, ALL_ROLES, body, req_dt
from response import success, list_response, created_sorted
from serializers import ser_snapshot
from services.snapshot import run_sweep, finalize_sla

bp = Blueprint("snapshots", __name__)


def get_snapshot(sid):
    s = db.snapshots.get(sid)
    if not s:
        raise ApiError(ERR_NOT_FOUND, "OpsSnapshot not found", 404)
    return s


@bp.route("/ops-snapshots", methods=["POST"])
def create():
    require_roles("MeterOpsAdmin")
    data = body()
    snapshot_at = req_dt(data, "snapshot_at")
    rec = {
        "snapshot_at": snapshot_at,
        "snapshot_status": "DRAFT",
        "eligible_stop_count": 0,
        "covered_stop_count": 0,
        "backlog_count": 0,
        "backlog_aged_7plus_count": 0,
        "estimated_read_count": 0,
        "validated_read_count": 0,
        "read_rate_percent": None,
        "net_read_rate_percent": None,
        "sla_breach": None,
    }
    # run the pinned four-step sweep before stamping so the checkpoint is born
    # with its aggregates (version stays 1)
    run_sweep(rec)
    stamp_new(rec)
    db.snapshots[rec["id"]] = rec
    return success(ser_snapshot(rec), code=201)


@bp.route("/ops-snapshots", methods=["GET"])
def list_all():
    require_roles(*ALL_ROLES)
    items = list(db.snapshots.values())
    val = request.args.get("snapshot_status")
    if val is not None:
        items = [s for s in items if s["snapshot_status"] == val]
    return list_response([ser_snapshot(s) for s in created_sorted(items)])


@bp.route("/ops-snapshots/<sid>", methods=["GET"])
def get_one(sid):
    require_roles(*ALL_ROLES)
    return success(ser_snapshot(get_snapshot(sid)), code=200)


@bp.route("/ops-snapshots/<sid>/finalize", methods=["POST"])
def finalize(sid):
    require_roles("MeterOpsAdmin")
    s = get_snapshot(sid)
    if s["snapshot_status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, "Snapshot is not DRAFT", 409)
    finalize_sla(s)
    s["snapshot_status"] = "FINALIZED"
    touch(s)
    return success(ser_snapshot(s), code=200)
