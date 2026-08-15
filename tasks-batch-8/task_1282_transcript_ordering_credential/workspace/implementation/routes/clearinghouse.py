"""ClearinghouseReportBatch endpoints."""
from flask import Blueprint, request

from db import DB, new_id, logical_now_iso
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_batch, ser_batch, sorted_created, stamp, sweep_batch, touch
from util import as_iso_dt, body, pagination_args, reject_unknown_fields, required

bp = Blueprint("clearinghouse", __name__)

OP_ROLES = ["RegistrarOperator"]
READ_ROLES = ["RegistrarAdmin", "RegistrarOperator", "RegistrarReviewer"]


@bp.post("/registrar/clearinghouse-batches")
def create_batch():
    auth(OP_ROLES)
    data = body()
    reject_unknown_fields(data, {"report_period_start", "report_period_end"})
    start = as_iso_dt(required(data, "report_period_start"), "report_period_start")
    end = as_iso_dt(required(data, "report_period_end"), "report_period_end")

    rec = {
        "id": new_id(),
        "report_period_start": start,
        "report_period_end": end,
        "status": "OPEN",
        "order_count": 0,
        "verification_count": 0,
        "transmitted_at": None,
        "_swept_order_ids": [],
        "_swept_verification_ids": [],
    }
    stamp(rec)
    DB["clearinghouse_batches"][rec["id"]] = rec
    sweep_batch(rec)
    return ok(ser_batch(rec), status=201)


@bp.get("/registrar/clearinghouse-batches")
def list_batches():
    auth(READ_ROLES)
    limit, offset = pagination_args()
    items = list(DB["clearinghouse_batches"].values())
    st = request.args.get("status")
    if st is not None:
        items = [b for b in items if b["status"] == st]
    items = sorted_created(items)
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_batch(b) for b in page], total, limit, offset)


@bp.get("/registrar/clearinghouse-batches/<bid>")
def get_one_batch(bid):
    auth(READ_ROLES)
    return ok(ser_batch(get_batch(bid)))


@bp.post("/registrar/clearinghouse-batches/<bid>/lock")
def lock_batch(bid):
    auth(OP_ROLES)
    rec = get_batch(bid)
    if rec["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Batch is not OPEN")
    # Lazily re-sweep at lock so membership reflects the current state.
    sweep_batch(rec)
    if rec["order_count"] + rec["verification_count"] == 0:
        raise ApiError("ERR_BATCH_EMPTY", 422, "Batch has no swept items")
    rec["status"] = "LOCKED"
    touch(rec)
    return ok(ser_batch(rec))


@bp.post("/registrar/clearinghouse-batches/<bid>/transmit")
def transmit_batch(bid):
    auth(OP_ROLES)
    rec = get_batch(bid)
    if rec["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", 409, "Batch is not LOCKED")
    rec["transmitted_at"] = logical_now_iso()
    rec["status"] = "TRANSMITTED"
    touch(rec)
    # Cascade: swept APPROVED VerificationRequests -> REPORTED.
    for vid in rec.get("_swept_verification_ids", []):
        vr = DB["verification_requests"].get(vid)
        if vr is not None and vr["status"] == "APPROVED":
            vr["status"] = "REPORTED"
            touch(vr)
    return ok(ser_batch(rec))


@bp.post("/registrar/clearinghouse-batches/<bid>/ack")
def ack_batch(bid):
    auth(OP_ROLES)
    rec = get_batch(bid)
    if rec["status"] != "TRANSMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Batch is not TRANSMITTED")
    rec["status"] = "ACKED"
    touch(rec)
    return ok(ser_batch(rec))


@bp.post("/registrar/clearinghouse-batches/<bid>/mark-failed")
def fail_batch(bid):
    auth(OP_ROLES)
    rec = get_batch(bid)
    if rec["status"] != "TRANSMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Batch is not TRANSMITTED")
    rec["status"] = "FAILED"
    touch(rec)
    # Compensating action: swept VerificationRequests this batch's transmit
    # moved to REPORTED revert to APPROVED so the next sweep re-includes them.
    for vid in rec.get("_swept_verification_ids", []):
        vr = DB["verification_requests"].get(vid)
        if vr is not None and vr["status"] == "REPORTED":
            vr["status"] = "APPROVED"
            touch(vr)
    # Membership unlocked — next sweep re-includes the same items.
    rec["_swept_order_ids"] = []
    rec["_swept_verification_ids"] = []
    return ok(ser_batch(rec))
