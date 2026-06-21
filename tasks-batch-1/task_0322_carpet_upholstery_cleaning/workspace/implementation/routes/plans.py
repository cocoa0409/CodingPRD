"""RecurringPlan endpoints (PRD §3.1).

Ownership: a RecurringPlan is owned by the customer in its customer_id. A
Customer-role mutation on a plan they do not own -> ERR_NOT_RESOURCE_OWNER.
"""
from __future__ import annotations

from flask import Blueprint, g

import db
from errors import APIError, ERR_NOT_RESOURCE_OWNER
from middleware import is_customer, require
from response import ok_object
from services.common import (
    get_json_body,
    init_common,
    public,
    require_enum,
    require_str,
    touch,
)
from services.lookups import get_customer, get_plan

bp = Blueprint("plans", __name__)

CADENCES = {"MONTHLY", "QUARTERLY", "SEMIANNUAL"}


@bp.post("/recurring-plans")
def create_plan():
    require(["Customer", "ServiceManager"])
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    cadence = require_enum(body, "cadence", CADENCES)

    # existence of body-referenced customer (priority 3, 404)
    get_customer(customer_id)

    # ownership: a Customer may only create a plan for themselves (priority 5)
    if is_customer() and customer_id != g.user_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Customer does not own this plan")

    record = init_common({
        "customer_id": customer_id,
        "cadence": cadence,
        "completed_visit_count": 0,
        "status": "ACTIVE",
    })
    db.recurring_plans[record["id"]] = record
    return ok_object(public(record), 201)


@bp.get("/recurring-plans/<pid>")
def get_plan_ep(pid):
    require(["Customer", "ServiceManager"])
    p = get_plan(pid)
    return ok_object(public(p), 200)


@bp.post("/recurring-plans/<pid>/pause")
def pause_plan(pid):
    require(["Customer", "ServiceManager"])
    p = get_plan(pid)
    # ownership (priority 5)
    if is_customer() and p["customer_id"] != g.user_id:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Customer does not own this plan")
    p["status"] = "PAUSED"
    touch(p)
    return ok_object(public(p), 200)
