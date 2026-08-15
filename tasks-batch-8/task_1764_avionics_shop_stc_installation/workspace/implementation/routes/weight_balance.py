"""Weight & balance revision endpoints: compute (INCREMENTAL / FULL_REWEIGH)
and inspector acceptance with CG-envelope gating."""
from flask import Blueprint, request

import db
import errors
from db import touch
from middleware import (
    authenticate,
    body,
    opt_added_items,
    opt_num,
    pagination_args,
    paginate,
    req_enum,
    req_str,
    require_role,
)
from response import success
from serializers import ser_wb_revision
from services.core import children_of, compute_weight_balance

bp = Blueprint("weight_balance", __name__)

METHODS = {"INCREMENTAL", "FULL_REWEIGH"}
COMPUTABLE_WO_STATES = ("INSTALLATION", "TESTING")


def _get_revision(weightBalanceRevisionId):
    r = db.wb_revisions.get(weightBalanceRevisionId)
    if r is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Weight & balance revision not found")
    return r


@bp.post("/avionics/weight-balance-revisions")
def create_wb_revision():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    work_order_id = req_str(b, "work_order_id")
    method = req_enum(b, "method", METHODS)
    added_items = opt_added_items(b)
    removed_weight_lb = opt_num(b, "removed_weight_lb", 0)
    if removed_weight_lb < 0:
        errors.raise_err(errors.ERR_VALIDATION, "removed_weight_lb must be zero or more")
    removed_arm_present = b.get("removed_arm_in") is not None
    # removed_arm_in present exactly when removed_weight_lb > 0
    if removed_weight_lb > 0 and not removed_arm_present:
        errors.raise_err(
            errors.ERR_VALIDATION, "removed_arm_in is required when removed_weight_lb > 0"
        )
    if removed_weight_lb == 0 and removed_arm_present:
        errors.raise_err(
            errors.ERR_VALIDATION, "removed_arm_in must be absent when removed_weight_lb is 0"
        )
    removed_arm_in = opt_num(b, "removed_arm_in") if removed_arm_present else None

    wo = db.work_orders.get(work_order_id)
    if wo is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Work order not found")
    if wo.status not in COMPUTABLE_WO_STATES:
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Work order must be in INSTALLATION or TESTING",
        )

    computed = compute_weight_balance(
        wo, method, added_items, removed_weight_lb, removed_arm_in
    )
    r = db.new_entity(
        work_order_id=wo.id,
        method=method,
        added_items=added_items,
        removed_weight_lb=removed_weight_lb,
        removed_arm_in=removed_arm_in,
        new_empty_weight_lb=computed["new_empty_weight_lb"],
        new_moment_lb_in=computed["new_moment_lb_in"],
        new_arm_in=computed["new_arm_in"],
        cg_within_limits=computed["cg_within_limits"],
        status="COMPUTED",
    )
    db.wb_revisions[r.id] = r
    return success(ser_wb_revision(r), 201)


@bp.get("/avionics/weight-balance-revisions/<weightBalanceRevisionId>")
def get_wb_revision(weightBalanceRevisionId):
    authenticate()
    return success(ser_wb_revision(_get_revision(weightBalanceRevisionId)), 200)


@bp.get("/avionics/weight-balance-revisions")
def list_wb_revisions():
    authenticate()
    limit, offset = pagination_args()
    work_order_id = request.args.get("work_order_id")
    items = sorted(db.wb_revisions.values(), key=lambda r: r._seq)
    if work_order_id is not None:
        items = [r for r in items if r.work_order_id == work_order_id]
    page, meta = paginate([ser_wb_revision(r) for r in items], limit, offset)
    return success(page, 200, meta)


@bp.post("/avionics/weight-balance-revisions/<weightBalanceRevisionId>/accept")
def accept_wb_revision(weightBalanceRevisionId):
    _, role = authenticate()
    require_role(role, {"Inspector"})
    r = _get_revision(weightBalanceRevisionId)
    wo = db.work_orders[r.work_order_id]
    if r.status != "COMPUTED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Only a COMPUTED revision can be accepted")
    if wo.status not in COMPUTABLE_WO_STATES:
        errors.raise_err(
            errors.ERR_INVALID_STATE,
            "Parent work order must be in INSTALLATION or TESTING",
        )
    if not r.cg_within_limits:
        errors.raise_err(
            errors.ERR_CG_OUT_OF_LIMITS,
            "New arm falls outside the aircraft CG envelope",
        )
    # accepting supersedes whichever revision was previously ACCEPTED
    for prior in children_of(db.wb_revisions, wo.id):
        if prior.id != r.id and prior.status == "ACCEPTED":
            prior.status = "SUPERSEDED"
            touch(prior)
    r.status = "ACCEPTED"
    touch(r)
    return success(ser_wb_revision(r), 200)
