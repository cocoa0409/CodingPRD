"""RatePlan endpoints + rate-plan-scoped zone list."""
from __future__ import annotations

from flask import Blueprint, request

import db
from middleware import get_json_body, require_auth
from response import ok_object
from services.common import list_response, lookup, require_int, require_string
from services.serialize import public

bp = Blueprint("rate_plans", __name__)

ALL_ROLES = ["FacilityAdmin", "EnforcementOfficer", "Merchant", "Motorist"]


@bp.post("/parking/rate-plans")
def create_rate_plan():
    require_auth(["FacilityAdmin"])()
    body = get_json_body()
    name = require_string(body, "name")
    hourly_cents = require_int(body, "hourly_cents", required=True, minimum=0)
    daily_cap_cents = require_int(body, "daily_cap_cents", required=True, minimum=0)
    monthly_permit_cents = require_int(body, "monthly_permit_cents", required=True, minimum=0)
    grace_minutes = require_int(body, "grace_minutes", required=False, minimum=0, default=15)

    rp = db.stamp_common(
        {
            "name": name,
            "hourly_cents": hourly_cents,
            "daily_cap_cents": daily_cap_cents,
            "monthly_permit_cents": monthly_permit_cents,
            "grace_minutes": grace_minutes,
        }
    )
    db.rate_plans[rp["id"]] = rp
    return ok_object(public(rp), 201)


@bp.get("/parking/rate-plans/<rid>")
def read_rate_plan(rid):
    require_auth(ALL_ROLES)()
    rp = lookup(db.rate_plans, rid)
    return ok_object(public(rp), 200)


@bp.get("/parking/rate-plans/<rid>/zones")
def list_rate_plan_zones(rid):
    require_auth(["FacilityAdmin", "EnforcementOfficer"])()
    lookup(db.rate_plans, rid)
    items = [z for z in db.zones.values() if z["rate_plan_id"] == rid]
    return list_response(items, request.args)
