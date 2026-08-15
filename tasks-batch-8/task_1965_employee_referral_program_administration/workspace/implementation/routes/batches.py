"""Payroll batches: OPEN -> SEALED -> EXPORTED -> CONFIRMED_PAID (or CANCELLED),
with OCC-guarded milestone attach/detach."""

from flask import Blueprint, request, g

from db import store
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, ERR_STALE_VERSION,
                    ERR_BATCH_NOT_OPEN, ERR_MILESTONE_NOT_BATCHABLE)
from middleware import require_role
import services as svc
from services import new_entity, touch
from util import (req_str, respond_object, respond_list, parse_pagination,
                  paginate, is_int)
from views import batch_view

bp = Blueprint("batches", __name__)

READ_ROLES = ("PlatformAdmin", "TalentAdmin", "PayrollProcessor")


def _get_batch(batch_id):
    b = store.batches.get(batch_id)
    if b is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Payroll batch not found")
    return b


def _batch_state_gate(batch, allowed_from, action_desc):
    if batch["status"] in svc.BATCH_TERMINAL:
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       "Payroll batch is in terminal state %s" % batch["status"])
    if batch["status"] not in allowed_from:
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Cannot %s a batch in state %s" % (action_desc, batch["status"]))


def _occ_expected(body):
    expected = body.get("expected_payroll_batch_version")
    if not is_int(expected):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "expected_payroll_batch_version is required and must be an integer")
    return expected


@bp.post("/erp/payroll-batches")
def create_batch():
    body = request.get_json(silent=True) or {}
    period_label = req_str(body, "period_label")
    require_role("PayrollProcessor")
    b = new_entity(store.batches, {
        "period_label": period_label,
        "status": "OPEN",
    })
    return respond_object(batch_view(b), status=201)


@bp.get("/erp/payroll-batches")
def list_batches():
    require_role(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = svc.sort_by_created(store.batches.values())
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, total = paginate(items, limit, offset)
    return respond_list([batch_view(b) for b in page], total, limit, offset)


@bp.get("/erp/payroll-batches/<batch_id>")
def get_batch(batch_id):
    require_role(*READ_ROLES)
    return respond_object(batch_view(_get_batch(batch_id)))


@bp.post("/erp/payroll-batches/<batch_id>/milestones")
def add_milestone(batch_id):
    body = request.get_json(silent=True) or {}
    milestone_id = body.get("milestone_id")
    if not isinstance(milestone_id, str) or not milestone_id:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: milestone_id")
    expected = _occ_expected(body)
    require_role("PayrollProcessor")
    batch = _get_batch(batch_id)
    # OCC before batch-open / milestone-attachability checks (PRD 2.7).
    if expected != batch["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_payroll_batch_version %s does not match current version %s"
                       % (expected, batch["version"]))
    if batch["status"] != "OPEN":
        raise ApiError(ERR_BATCH_NOT_OPEN, 409,
                       "Payroll batch is not OPEN (currently %s)" % batch["status"])
    m = store.milestones.get(milestone_id)
    if m is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Milestone not found")
    attachable = (
        (m["status"] == "APPROVED" and m["payroll_batch_id"] is None)
        or (m["status"] == "CLAWED_BACK" and m["recovery_status"] == "PENDING"
            and m["payroll_batch_id"] is None)
    )
    if not attachable:
        raise ApiError(ERR_MILESTONE_NOT_BATCHABLE, 409,
                       "Milestone cannot be attached from status %s" % m["status"])
    if m["status"] == "APPROVED":
        m["status"] = "BATCHED"
    # Recovery lines link without changing CLAWED_BACK status.
    m["payroll_batch_id"] = batch["id"]
    touch(m)
    touch(batch)  # totals recompute; batch version increments
    return respond_object(batch_view(batch))


@bp.post("/erp/payroll-batches/<batch_id>/milestones/<milestone_id>/remove")
def remove_milestone(batch_id, milestone_id):
    body = request.get_json(silent=True) or {}
    expected = _occ_expected(body)
    require_role("PayrollProcessor")
    # Left-to-right path existence (PRD 2.9).
    batch = _get_batch(batch_id)
    m = store.milestones.get(milestone_id)
    if m is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Milestone not found")
    if expected != batch["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_payroll_batch_version %s does not match current version %s"
                       % (expected, batch["version"]))
    if batch["status"] != "OPEN":
        raise ApiError(ERR_BATCH_NOT_OPEN, 409,
                       "Payroll batch is not OPEN (currently %s)" % batch["status"])
    if m["payroll_batch_id"] != batch["id"]:
        raise ApiError(ERR_MILESTONE_NOT_BATCHABLE, 409,
                       "Milestone is not attached to this batch")
    if m["status"] == "BATCHED":
        m["status"] = "APPROVED"
    # Recovery lines detach unchanged (still CLAWED_BACK / recovery PENDING).
    m["payroll_batch_id"] = None
    touch(m)
    touch(batch)
    return respond_object(batch_view(batch))


@bp.post("/erp/payroll-batches/<batch_id>/seal")
def seal_batch(batch_id):
    require_role("PayrollProcessor")
    batch = _get_batch(batch_id)
    _batch_state_gate(batch, ("OPEN",), "seal")
    batch["status"] = "SEALED"
    touch(batch)
    return respond_object(batch_view(batch))


@bp.post("/erp/payroll-batches/<batch_id>/export")
def export_batch(batch_id):
    require_role("PayrollProcessor")
    batch = _get_batch(batch_id)
    _batch_state_gate(batch, ("SEALED",), "export")
    # Deterministic export order: earned_at ASC, tie-break Referral.created_at ASC.
    batch["status"] = "EXPORTED"
    touch(batch)
    return respond_object(batch_view(batch))


@bp.post("/erp/payroll-batches/<batch_id>/confirm-paid")
def confirm_paid(batch_id):
    require_role("TalentAdmin")  # segregation of duties: processor prepares, admin confirms
    batch = _get_batch(batch_id)
    _batch_state_gate(batch, ("EXPORTED",), "confirm-paid")
    now = store.clock
    for m in svc.sort_by_created(store.milestones.values()):
        if m["payroll_batch_id"] != batch["id"]:
            continue
        if m["status"] == "BATCHED":
            m["status"] = "PAID"
            m["_paid_at"] = now
            m["payroll_batch_id"] = None  # carried only while BATCHED
            touch(m)
        elif m["status"] == "CLAWED_BACK" and m["recovery_status"] == "PENDING":
            m["recovery_status"] = "RECOVERED"
            touch(m)
    batch["status"] = "CONFIRMED_PAID"
    touch(batch)
    return respond_object(batch_view(batch))


@bp.post("/erp/payroll-batches/<batch_id>/cancel")
def cancel_batch(batch_id):
    require_role("PayrollProcessor")
    batch = _get_batch(batch_id)
    _batch_state_gate(batch, ("OPEN",), "cancel")
    for m in svc.sort_by_created(store.milestones.values()):
        if m["payroll_batch_id"] != batch["id"]:
            continue
        if m["status"] == "BATCHED":
            m["status"] = "APPROVED"
        # Recovery lines stay CLAWED_BACK with recovery PENDING.
        m["payroll_batch_id"] = None
        touch(m)
    batch["status"] = "CANCELLED"
    touch(batch)
    return respond_object(batch_view(batch))
