"""Deposit endpoints: pledge, list, post, refund (PRD 3.6)."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, authenticate
from response import ok_list, ok_object
from services import (
    case_deposits,
    deposit_refund_amount,
    recompute_case,
    regress_case_if_cleared,
)
from util import (
    base_record,
    get_body,
    now_iso,
    paginate,
    req_enum,
    req_int,
    serialize,
    touch,
)

bp = Blueprint("deposits", __name__)


def get_deposit_or_404(did):
    rec = db.deposits.get(did)
    if rec is None:
        raise not_found("deposit not found")
    return rec


@bp.post("/clearance/cases/<cid>/deposits")
def create_deposit(cid):
    authenticate(["FinancialCounselor"])
    if cid not in db.cases:
        raise not_found("case not found")
    b = get_body()
    amount_cents = req_int(b, "amount_cents")
    if amount_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be > 0", 400)
    method = req_enum(b, "method", ("CARD", "CHECK", "CASH"))
    rec = base_record()
    rec.update({
        "case_id": cid,
        "amount_cents": amount_cents,
        "method": method,
        "status": "PLEDGED",
        "posted_at": None,
        "applied_amount_cents": None,
        "refund_amount_cents": None,
        "refund_reason": None,
    })
    db.deposits[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/clearance/cases/<cid>/deposits")
def list_deposits(cid):
    authenticate(ALL_ROLES)
    if cid not in db.cases:
        raise not_found("case not found")
    page, meta = paginate(case_deposits(cid))
    return ok_list([serialize(d) for d in page], meta)


@bp.post("/clearance/deposits/<did>/post")
def post_deposit(did):
    authenticate(["FinancialCounselor"])
    dep = get_deposit_or_404(did)
    if dep["status"] != "PLEDGED":
        raise invalid_state("only a PLEDGED deposit can be posted")
    dep["status"] = "POSTED"
    dep["posted_at"] = now_iso()
    touch(dep)
    # ledger sync: recompute the case immediately
    case = db.cases[dep["case_id"]]
    if recompute_case(case):
        touch(case)
    return ok_object(serialize(dep))


@bp.post("/clearance/deposits/<did>/refund")
def refund_deposit(did):
    authenticate(["ClearanceSupervisor"])
    dep = get_deposit_or_404(did)
    if dep["status"] != "POSTED":
        raise invalid_state("only a POSTED deposit can be refunded")
    case = db.cases[dep["case_id"]]
    dep["refund_amount_cents"] = deposit_refund_amount(dep["amount_cents"], case["service_date"])
    dep["refund_reason"] = "SERVICE_CANCELLED"
    dep["status"] = "REFUNDED"
    touch(dep)
    # the full pledged amount leaves the deposit ledger (retained fee included)
    recompute_case(case)
    regress_case_if_cleared(case)
    touch(case)
    return ok_object(serialize(dep))
