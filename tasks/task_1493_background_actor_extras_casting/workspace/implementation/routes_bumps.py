"""BumpAdjustment endpoints (SoD: decider must differ from requester)."""
from flask import Blueprint, request

from db import STORE
from domain import LOOK_CATEGORIES, _base, ser_bump, touch
from errors import (
    ApiError,
    ERR_BUMP_ADJUSTMENT_NOT_FOUND,
    ERR_BUMP_INVALID_STATE,
    ERR_BUMP_VOUCHER_LOCKED,
    ERR_SOD_SELF_APPROVAL,
)
from middleware import ALL_ROLES, auth, body, opt_str, req_enum, req_int, req_str
from response import ok_list, ok_obj, paginate
from routes_vouchers import get_voucher
from services import recompute_batch_and_exposure, voucher_bumps

bp = Blueprint("bump_adjustments", __name__)


def get_bump(bid):
    b = STORE.bump_adjustments.get(bid)
    if b is None:
        raise ApiError(ERR_BUMP_ADJUSTMENT_NOT_FOUND, 404, "Bump adjustment not found")
    return b


@bp.post("/central-casting/bump-adjustments")
def create_bump():
    user_id, _ = auth(["CastingAssociate"])
    data = body()
    voucher_id = req_str(data, "voucher_id")
    voucher = get_voucher(voucher_id)
    category = req_enum(data, "category", LOOK_CATEGORIES)
    amount = req_int(data, "amount_cents", minimum=1)
    justification = opt_str(data, "justification")
    if voucher["status"] not in ("DRAFT", "ISSUED", "DISPUTED", "REJECTED"):
        raise ApiError(
            ERR_BUMP_VOUCHER_LOCKED,
            409,
            "Bumps cannot be filed against a SUBMITTED or PAID voucher",
        )
    b = _base()
    b.update(
        {
            "voucher_id": voucher_id,
            "category": category,
            "amount_cents": amount,
            "justification": justification,
            "requested_by_user_id": user_id,
            "decided_by_user_id": None,
            "status": "PENDING",
        }
    )
    STORE.bump_adjustments[b["id"]] = b
    return ok_obj(ser_bump(b), code=201)


@bp.get("/central-casting/bump-adjustments")
def list_bumps():
    auth(ALL_ROLES)
    rows = sorted(STORE.bump_adjustments.values(), key=lambda b: b["_seq"])
    voucher_id = request.args.get("voucher_id")
    status = request.args.get("status")
    if voucher_id is not None:
        rows = [b for b in rows if b["voucher_id"] == voucher_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    page, total, limit, offset = paginate(rows)
    return ok_list([ser_bump(b) for b in page], total, limit, offset)


@bp.get("/central-casting/bump-adjustments/<bid>")
def get_bump_route(bid):
    auth(ALL_ROLES)
    return ok_obj(ser_bump(get_bump(bid)))


@bp.post("/central-casting/bump-adjustments/<bid>/approve")
def approve_bump(bid):
    user_id, _ = auth(["CastingDirector"])
    b = get_bump(bid)
    # SoD (pipeline step 4) precedes state preconditions (step 8).
    if user_id == b["requested_by_user_id"]:
        raise ApiError(
            ERR_SOD_SELF_APPROVAL, 403, "The bump decider must differ from the requester"
        )
    if b["status"] != "PENDING":
        raise ApiError(ERR_BUMP_INVALID_STATE, 409, "Only a PENDING bump can be approved")
    voucher = STORE.vouchers[b["voucher_id"]]
    if voucher["status"] in ("SUBMITTED", "PAID"):
        raise ApiError(
            ERR_BUMP_VOUCHER_LOCKED,
            409,
            "The voucher is locked (SUBMITTED or PAID)",
        )
    b["status"] = "APPROVED"
    b["decided_by_user_id"] = user_id
    touch(b)
    if voucher["status"] == "ISSUED":
        # Approval immediately re-prices an issued voucher: bumps total and gross.
        voucher["bumps_total_cents"] = voucher_bumps(voucher["id"], ("APPROVED",))
        voucher["gross_total_cents"] = (
            (voucher.get("base_wages_cents") or 0)
            + (voucher.get("ot_wages_cents") or 0)
            + (voucher.get("meal_penalty_cents") or 0)
            + voucher["bumps_total_cents"]
        )
        touch(voucher)
        if voucher.get("payroll_batch_id"):
            batch = STORE.payroll_batches.get(voucher["payroll_batch_id"])
            if batch is not None and batch["status"] == "OPEN":
                recompute_batch_and_exposure(batch)
    return ok_obj(ser_bump(b))


@bp.post("/central-casting/bump-adjustments/<bid>/reject")
def reject_bump(bid):
    user_id, _ = auth(["CastingDirector"])
    b = get_bump(bid)
    if user_id == b["requested_by_user_id"]:
        raise ApiError(
            ERR_SOD_SELF_APPROVAL, 403, "The bump decider must differ from the requester"
        )
    if b["status"] != "PENDING":
        raise ApiError(ERR_BUMP_INVALID_STATE, 409, "Only a PENDING bump can be rejected")
    b["status"] = "REJECTED"
    b["decided_by_user_id"] = user_id
    touch(b)
    return ok_obj(ser_bump(b))
