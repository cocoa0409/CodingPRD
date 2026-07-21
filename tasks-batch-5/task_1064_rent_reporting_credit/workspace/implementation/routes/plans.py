from flask import Blueprint

import store
from common import (ApiError, authorize, ok_object, serialize, get_body,
                    require_str, require_enum, require_int)

bp = Blueprint("plans", __name__)


@bp.post("/api/subscription-plans")
def create_plan():
    uid, role = authorize(["PlatformAdmin"])
    body = get_body()
    name = require_str(body, "name")
    tier = require_enum(body, "tier", ["BASIC", "PLUS", "PREMIUM"])
    monthly_fee_cents = require_int(body, "monthly_fee_cents")
    if monthly_fee_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST", "monthly_fee_cents must be >= 0")
    included = require_int(body, "back_reporting_included_months")
    if included < 0:
        raise ApiError("ERR_INVALID_REQUEST", "back_reporting_included_months must be >= 0")
    p = store.base_fields()
    p.update({
        "name": name,
        "tier": tier,
        "monthly_fee_cents": monthly_fee_cents,
        "back_reporting_included_months": included,
    })
    store.plans[p["id"]] = p
    return ok_object(serialize(p), 201)


@bp.get("/api/subscription-plans/<plan_id>")
def get_plan(plan_id):
    uid, role = authorize(["PlatformAdmin", "Tenant"])
    p = store.plans.get(plan_id)
    if p is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", "plan not found")
    return ok_object(serialize(p))
