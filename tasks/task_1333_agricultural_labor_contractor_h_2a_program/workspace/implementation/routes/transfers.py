"""Transfer requests."""

from datetime import timedelta

from flask import Blueprint, g, request

import calc
from calc import iso
from common import (ALL_ROLES, ApiError, auth, body, clock_date, created_order,
                    forbid_ownership, get_or_404, invalid, ok, ok_list,
                    paginate, stamp_new, touch)
from services import (create_recon, recompute_recon, recon_for, ser_transfer,
                      vacate_housing_for_assignment)
from store import db

bp = Blueprint("transfers", __name__)


def _transfer(rid):
    return get_or_404(db.transfer_requests, rid,
                      "ERR_TRANSFER_REQUEST_NOT_FOUND", "transfer request")


@bp.post("/h2a/transfer-requests")
@auth("ContractorAdmin", "GrowerRep")
def create_transfer():
    b = body()
    worker_id = b.get("worker_id")
    from_assignment_id = b.get("from_assignment_id")
    to_order_id = b.get("to_job_order_id")

    src = None
    if from_assignment_id is not None:
        src = db.worker_assignments.get(from_assignment_id)
    # GrowerRep ownership (priority 3) is anchored on the source order.
    if g.user_role == "GrowerRep" and src is not None:
        src_order = db.job_orders.get(src["job_order_id"])
        if src_order is None or src_order["grower_id"] != g.user_id:
            raise forbid_ownership(
                "GrowerRep may request transfers only away from its own "
                "grower's orders")

    if worker_id is None:
        raise invalid("worker_id is required")
    get_or_404(db.workers, worker_id, "ERR_WORKER_NOT_FOUND", "worker")
    if from_assignment_id is None:
        raise invalid("from_assignment_id is required")
    if src is None:
        raise ApiError("ERR_WORKER_ASSIGNMENT_NOT_FOUND", 404,
                       "worker assignment not found")
    if to_order_id is None:
        raise invalid("to_job_order_id is required")
    target = get_or_404(db.job_orders, to_order_id, "ERR_JOB_ORDER_NOT_FOUND",
                        "job order")

    if src["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE", 409,
                       "source assignment must be ACTIVE")
    if target["status"] != "ACTIVE":
        raise ApiError("ERR_JOB_ORDER_INVALID_STATE", 409,
                       "target job order must be ACTIVE")
    src_order = db.job_orders[src["job_order_id"]]
    if target["grower_id"] == src_order["grower_id"]:
        raise ApiError("ERR_SAME_GROWER_TRANSFER", 409,
                       "target order belongs to the same grower")
    if any(t["worker_id"] == worker_id
           and t["status"] in ("PENDING", "GROWER_APPROVED")
           for t in db.transfer_requests.values()):
        raise ApiError("ERR_DUPLICATE_ACTIVE_TRANSFER", 409,
                       "worker already has an active transfer request")
    reason = b.get("reason")
    if not isinstance(reason, str) or reason not in calc.TRANSFER_REASON_ENUM:
        raise invalid("reason must be CONTRACT_IMPOSSIBILITY, GROWER_REQUEST, "
                      "or WORKER_REQUEST")
    rec = {
        "worker_id": worker_id,
        "from_assignment_id": src["id"],
        "to_job_order_id": target["id"],
        "reason": reason,
        "requested_by_user_id": g.user_id,
        "status": "PENDING",
    }
    stamp_new(rec)
    db.transfer_requests[rec["id"]] = rec
    return ok(ser_transfer(rec), 201)


@bp.get("/h2a/transfer-requests")
@auth(*ALL_ROLES)
def list_transfers():
    q = request.args
    rows = list(db.transfer_requests.values())
    for key in ("worker_id", "from_assignment_id", "to_job_order_id",
                "status"):
        if q.get(key) is not None:
            rows = [t for t in rows if t[key] == q.get(key)]
    rows = created_order(rows)
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_transfer(t) for t in page], total, limit, offset)


@bp.get("/h2a/transfer-requests/<transferRequestId>")
@auth(*ALL_ROLES)
def get_transfer(transferRequestId):
    return ok(ser_transfer(_transfer(transferRequestId)))


def _target_grower_owns(t):
    target = db.job_orders.get(t["to_job_order_id"])
    return target is not None and target["grower_id"] == g.user_id


@bp.post("/h2a/transfer-requests/<transferRequestId>/grower-approve")
@auth("GrowerRep")
def grower_approve(transferRequestId):
    t = db.transfer_requests.get(transferRequestId)
    if t is not None and not _target_grower_owns(t):
        raise forbid_ownership(
            "GrowerRep may approve only transfers inbound to its own grower")
    t = _transfer(transferRequestId)
    if t["status"] != "PENDING":
        raise ApiError("ERR_TRANSFER_INVALID_STATE", 409,
                       "transfer request is not PENDING")
    t["status"] = "GROWER_APPROVED"
    touch(t)
    return ok(ser_transfer(t))


@bp.post("/h2a/transfer-requests/<transferRequestId>/grower-reject")
@auth("GrowerRep")
def grower_reject(transferRequestId):
    t = db.transfer_requests.get(transferRequestId)
    if t is not None and not _target_grower_owns(t):
        raise forbid_ownership(
            "GrowerRep may reject only transfers inbound to its own grower")
    t = _transfer(transferRequestId)
    if t["status"] != "PENDING":
        raise ApiError("ERR_TRANSFER_INVALID_STATE", 409,
                       "transfer request is not PENDING")
    t["status"] = "REJECTED"
    touch(t)
    return ok(ser_transfer(t))


@bp.post("/h2a/transfer-requests/<transferRequestId>/finalize")
@auth("ContractorAdmin")
def finalize_transfer(transferRequestId):
    t = _transfer(transferRequestId)
    if t["status"] != "GROWER_APPROVED":
        raise ApiError("ERR_TRANSFER_INVALID_STATE", 409,
                       "transfer request is not GROWER_APPROVED")
    src = db.worker_assignments[t["from_assignment_id"]]
    if src["status"] != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE", 409,
                       "source assignment is no longer ACTIVE")
    target = db.job_orders[t["to_job_order_id"]]
    if target["status"] != "ACTIVE":
        raise ApiError("ERR_JOB_ORDER_INVALID_STATE", 409,
                       "target job order is no longer ACTIVE")

    effective = clock_date()
    # Source assignment -> TRANSFERRED_OUT, ended the day before.
    src["status"] = "TRANSFERRED_OUT"
    src["end_reason"] = "TRANSFERRED_OUT"
    src["ended_on"] = iso(effective - timedelta(days=1))
    touch(src)
    vacate_housing_for_assignment(src["id"], src["ended_on"])
    src_recon = recon_for(src["id"])
    if src_recon is not None and src_recon["status"] == "OPEN":
        recompute_recon(src_recon, final=False)
        touch(src_recon)
    # New ACTIVE assignment on the target order + fresh OPEN reconciliation.
    new_a = {
        "worker_id": t["worker_id"],
        "job_order_id": target["id"],
        "started_on": iso(effective),
        "ended_on": None,
        "end_reason": None,
        "status": "ACTIVE",
    }
    stamp_new(new_a)
    db.worker_assignments[new_a["id"]] = new_a
    create_recon(new_a)
    # Worker remains WORKING.
    t["status"] = "APPROVED"
    touch(t)
    return ok(ser_transfer(t))


@bp.post("/h2a/transfer-requests/<transferRequestId>/cancel")
@auth("ContractorAdmin", "GrowerRep")
def cancel_transfer(transferRequestId):
    t = db.transfer_requests.get(transferRequestId)
    if t is not None and g.user_role == "GrowerRep" \
            and t["requested_by_user_id"] != g.user_id:
        raise forbid_ownership(
            "GrowerRep may cancel only requests it originally filed")
    t = _transfer(transferRequestId)
    if t["status"] not in ("PENDING", "GROWER_APPROVED"):
        raise ApiError("ERR_TRANSFER_INVALID_STATE", 409,
                       "transfer request is not PENDING or GROWER_APPROVED")
    t["status"] = "CANCELLED"
    touch(t)
    return ok(ser_transfer(t))
