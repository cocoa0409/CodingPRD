"""Payment plan endpoints: draft, list, activate, payments, reinstate (PRD 3.8)."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_CURE_INSUFFICIENT,
    ERR_INVALID_REQUEST,
    ERR_NO_ACCEPTED_ESTIMATE,
    ERR_PAYMENT_EXCEEDS_OUTSTANDING,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, authenticate
from response import ok_list, ok_object
from services import (
    apply_payment_waterfall,
    build_installments,
    case_plans,
    fix_due_dates,
    locked_estimate,
    missed_payment_count,
    past_due_unpaid,
    plan_outstanding,
)
from util import (
    base_record,
    get_body,
    paginate,
    req_int,
    serialize,
    today,
    touch,
)

bp = Blueprint("payment_plans", __name__)


def get_plan_or_404(pid):
    plan = db.plans.get(pid)
    if plan is None:
        raise not_found("payment plan not found")
    return plan


def serialize_plan(plan):
    return serialize(plan, {"missed_payment_count": missed_payment_count(plan, today())})


@bp.post("/clearance/cases/<cid>/payment-plans")
def create_plan(cid):
    authenticate(["FinancialCounselor"])
    if cid not in db.cases:
        raise not_found("case not found")
    b = get_body()
    principal_cents = req_int(b, "principal_cents")
    if principal_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "principal_cents must be > 0", 400)
    num_installments = req_int(b, "num_installments")
    if not (2 <= num_installments <= 12):
        raise ApiError(ERR_INVALID_REQUEST, "num_installments must be in 2..12", 400)
    base, installments = build_installments(principal_cents, num_installments)
    rec = base_record()
    rec.update({
        "case_id": cid,
        "principal_cents": principal_cents,
        "num_installments": num_installments,
        "installment_amount_cents": base,
        "installments": installments,
        "principal_outstanding_cents": principal_cents,
        "status": "DRAFT",
    })
    db.plans[rec["id"]] = rec
    return ok_object(serialize_plan(rec), 201)


@bp.get("/clearance/cases/<cid>/payment-plans")
def list_plans(cid):
    authenticate(ALL_ROLES)
    if cid not in db.cases:
        raise not_found("case not found")
    page, meta = paginate(case_plans(cid))
    return ok_list([serialize_plan(p) for p in page], meta)


@bp.post("/clearance/payment-plans/<pid>/activate")
def activate_plan(pid):
    authenticate(["FinancialCounselor"])
    plan = get_plan_or_404(pid)
    if plan["status"] != "DRAFT":
        raise invalid_state("only a DRAFT payment plan can be activated")
    case = db.cases[plan["case_id"]]
    if locked_estimate(case) is None:
        raise ApiError(ERR_NO_ACCEPTED_ESTIMATE,
                       "the case has no ACCEPTED or FINALIZED estimate", 409)
    fix_due_dates(plan, today())
    plan["status"] = "ACTIVE"
    touch(plan)
    return ok_object(serialize_plan(plan))


@bp.post("/clearance/payment-plans/<pid>/payments")
def record_payment(pid):
    authenticate(["FinancialCounselor"])
    plan = get_plan_or_404(pid)
    b = get_body()
    amount_cents = req_int(b, "amount_cents")
    if amount_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "amount_cents must be > 0", 400)
    if plan["status"] not in ("ACTIVE", "DEFAULTED"):
        raise invalid_state("payments are accepted only on ACTIVE or DEFAULTED plans")
    if amount_cents > plan["principal_outstanding_cents"]:
        raise ApiError(ERR_PAYMENT_EXCEEDS_OUTSTANDING,
                       "amount_cents exceeds principal_outstanding_cents", 422)
    apply_payment_waterfall(plan, amount_cents)
    if plan["principal_outstanding_cents"] == 0:
        plan["status"] = "COMPLETED"
    touch(plan)
    return ok_object(serialize_plan(plan))


@bp.post("/clearance/payment-plans/<pid>/reinstate")
def reinstate_plan(pid):
    authenticate(["FinancialCounselor"])
    plan = get_plan_or_404(pid)
    b = get_body()
    cure_amount_cents = req_int(b, "cure_amount_cents")
    if cure_amount_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "cure_amount_cents must be > 0", 400)
    if plan["status"] != "DEFAULTED":
        raise invalid_state("only a DEFAULTED payment plan can be reinstated")
    due = past_due_unpaid(plan, today())
    if cure_amount_cents < due:
        raise ApiError(ERR_CURE_INSUFFICIENT,
                       "cure amount is below the sum of past-due unpaid installment balances", 409)
    apply_payment_waterfall(plan, cure_amount_cents)
    if plan["principal_outstanding_cents"] == 0:
        plan["status"] = "COMPLETED"
    else:
        plan["status"] = "ACTIVE"
    touch(plan)
    return ok_object(serialize_plan(plan))
