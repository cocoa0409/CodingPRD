"""Plan endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db
from common import (new_record, touch, serialize, get_body, require_str,
                    require_int, require_enum, require_field, must_exist, paginate)
from middleware import authenticate, require_roles
from response import success, list_success
from errors import err, ERR_INVALID_REQUEST

bp = Blueprint("plans", __name__)

CADENCES = {"MONTHLY", "QUARTERLY"}


@bp.post("/plans")
def create_plan():
    authenticate()
    require_roles("CurationAdmin")
    body = get_body()
    name = require_str(body, "name")
    cadence = require_enum(body, "cadence", CADENCES)
    period_price_cents = require_int(body, "period_price_cents", minimum=0)
    box_item_count = require_int(body, "box_item_count", minimum=1)

    prepaid_terms = body.get("prepaid_terms_offered", [])
    if prepaid_terms is None:
        prepaid_terms = []
    if not isinstance(prepaid_terms, list):
        raise err(ERR_INVALID_REQUEST, "prepaid_terms_offered must be an array.")
    for el in prepaid_terms:
        if isinstance(el, bool) or not isinstance(el, int) or el < 2:
            raise err(ERR_INVALID_REQUEST,
                      "Each prepaid_terms_offered element must be an integer >= 2.")

    discount = body.get("prepaid_discount_pct", 0)
    if discount is None:
        discount = 0
    if isinstance(discount, bool) or not isinstance(discount, (int, float)):
        raise err(ERR_INVALID_REQUEST, "prepaid_discount_pct must be a number.")
    if discount < 0 or discount >= 1:
        raise err(ERR_INVALID_REQUEST, "prepaid_discount_pct must be >= 0 and < 1.")

    plan = new_record({
        "name": name,
        "cadence": cadence,
        "period_price_cents": period_price_cents,
        "box_item_count": box_item_count,
        "prepaid_terms_offered": list(prepaid_terms),
        "prepaid_discount_pct": discount,
        "status": "ACTIVE",
    })
    db.plans[plan["id"]] = plan
    return success(serialize(plan), status=201)


@bp.get("/plans/<pid>")
def get_plan(pid):
    authenticate()
    require_roles("CurationAdmin", "Subscriber", "BillingOperator")
    plan = must_exist(db.plans, pid, "Plan")
    return success(serialize(plan))


@bp.get("/plans")
def list_plans():
    authenticate()
    require_roles("CurationAdmin", "Subscriber", "BillingOperator")
    records = list(db.plans.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.post("/plans/<pid>/retire")
def retire_plan(pid):
    authenticate()
    require_roles("CurationAdmin")
    plan = must_exist(db.plans, pid, "Plan")
    plan["status"] = "RETIRED"
    touch(plan)
    return success(serialize(plan))
