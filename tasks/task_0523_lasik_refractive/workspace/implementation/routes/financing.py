from flask import Blueprint

from db import db
from middleware import require_auth
from response import success
from helpers import touch, serialize, get_json_body, get_or_404, as_int
from errors import err

bp = Blueprint("financing", __name__)


@bp.post("/refractive/financing/<fid>/installments")
@require_auth(["Coordinator"])
def post_installment(fid):
    plan = get_or_404(db.financing, fid)
    body = get_json_body()
    amount = as_int(body, "amount_cents")
    if amount < 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be >= 0")

    case = db.cases[plan["case_id"]]

    # state gates: plan OPEN and case DEPOSIT_PAID
    if plan["status"] != "OPEN" or case["financial_status"] != "DEPOSIT_PAID":
        raise err("ERR_INVALID_STATE", "plan must be OPEN and case DEPOSIT_PAID")

    plan["amount_settled_cents"] += amount
    touch(plan)

    package = db.packages[case["package_id"]]
    if plan["amount_settled_cents"] >= package["base_price_cents"]:
        plan["status"] = "SETTLED"
        touch(plan)
        case["financial_status"] = "PAID_IN_FULL"
        touch(case)

    return success(serialize(plan), 201)


@bp.get("/refractive/financing/<fid>")
@require_auth(["Coordinator", "Patient"])
def get_financing(fid):
    return success(serialize(get_or_404(db.financing, fid)), 200)
