"""PaymentPlan endpoints: create, get, list-by-account, cure, terminate
(PRD 3.7)."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_CATCH_UP_REQUIRED,
    ERR_INVALID_REQUEST,
    ERR_PLAN_NOT_IN_DEFAULT,
    not_found,
)
from middleware import (
    ROLE_COLLECTOR,
    ROLE_COUNSELOR,
    ROLE_OFFICER,
    authenticate,
)
from response import ok_list, ok_object
from services import (
    MAX_INSTALLMENTS,
    installments_paid_count,
    serialize_plan,
)
from util import (
    base_record,
    get_body,
    paginate,
    parse_dt,
    req_date,
    req_int,
    req_str,
    touch,
)

bp = Blueprint("payment_plans", __name__)

_READ_ROLES = [ROLE_COLLECTOR, ROLE_COUNSELOR, ROLE_OFFICER]


def get_plan_or_404(plan_id):
    p = db.payment_plans.get(plan_id)
    if p is None:
        raise not_found("payment plan not found")
    return p


@bp.post("/self-pay/payment-plans")
def create_payment_plan():
    authenticate([ROLE_COLLECTOR, ROLE_COUNSELOR])
    b = get_body()
    account_id = req_str(b, "account_id")
    from routes_accounts import get_account_or_404
    get_account_or_404(account_id)
    installment_amount_cents = req_int(b, "installment_amount_cents")
    if installment_amount_cents <= 0:
        raise ApiError(ERR_INVALID_REQUEST,
                       "installment_amount_cents must be > 0", 400)
    installment_count = req_int(b, "installment_count")
    if not (2 <= installment_count <= MAX_INSTALLMENTS):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "installment_count must be between 2 and %d" % MAX_INSTALLMENTS,
            400,
        )
    first_installment_due = req_date(b, "first_installment_due")

    rec = base_record()
    rec.update({
        "account_id": account_id,
        "installment_amount_cents": installment_amount_cents,
        "installment_count": installment_count,
        "first_installment_due": first_installment_due,
        "missed_installment_count": 0,
        "default_flagged_at": None,
        "status": "ACTIVE",
    })
    db.payment_plans[rec["id"]] = rec
    return ok_object(serialize_plan(rec), 201)


@bp.get("/self-pay/payment-plans/<plan_id>")
def get_payment_plan(plan_id):
    authenticate(_READ_ROLES)
    return ok_object(serialize_plan(get_plan_or_404(plan_id)))


@bp.get("/self-pay/accounts/<account_id>/payment-plans")
def list_plans_for_account(account_id):
    authenticate(_READ_ROLES)
    from routes_accounts import get_account_or_404
    get_account_or_404(account_id)
    items = [p for p in db.payment_plans.values() if p["account_id"] == account_id]
    page, meta = paginate(items)
    return ok_list([serialize_plan(p) for p in page], meta)


@bp.post("/self-pay/payment-plans/<plan_id>/cure")
def cure_payment_plan(plan_id):
    authenticate([ROLE_COLLECTOR])
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "IN_DEFAULT":
        raise ApiError(ERR_PLAN_NOT_IN_DEFAULT,
                       "cure requires plan status IN_DEFAULT", 409)
    # a qualifying catch-up payment: an INSTALLMENT recovery on this plan,
    # posted since default_flagged_at, of at least missed * installment amount
    flagged_at = parse_dt(plan["default_flagged_at"])
    required_cents = plan["missed_installment_count"] * plan["installment_amount_cents"]
    qualifying = False
    for r in db.recovery_transactions.values():
        if (r["payment_kind"] == "INSTALLMENT"
                and r.get("payment_plan_id") == plan_id
                and parse_dt(r["posted_at"]) >= flagged_at
                and r["amount_cents"] >= required_cents):
            qualifying = True
            break
    if not qualifying:
        raise ApiError(
            ERR_CATCH_UP_REQUIRED,
            "cure requires a catch-up installment payment posted since "
            "default_flagged_at of at least missed_installment_count times "
            "installment_amount_cents",
            422,
        )
    # CURED is transient audit prose; the persisted post-cure state is ACTIVE
    plan["missed_installment_count"] = 0
    plan["default_flagged_at"] = None
    plan["status"] = "ACTIVE"
    touch(plan)
    return ok_object(serialize_plan(plan))


@bp.post("/self-pay/payment-plans/<plan_id>/terminate")
def terminate_payment_plan(plan_id):
    authenticate([ROLE_OFFICER])
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "IN_DEFAULT":
        raise ApiError(ERR_PLAN_NOT_IN_DEFAULT,
                       "terminate requires plan status IN_DEFAULT", 409)
    plan["status"] = "TERMINATED_DEFAULT"
    touch(plan)
    return ok_object(serialize_plan(plan))
