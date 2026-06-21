"""MembershipPlan routes: create, fetch, list (PRD §3.1)."""
from flask import Blueprint, request

import db
from lookups import get_or_404, get_salon
from response import success
from util import stamp_create, public
import validate as v
from routes.common import auth, json_body, list_response

bp = Blueprint("membership_plans", __name__)


@bp.post("/membership-plans")
def create_plan():
    auth(("SalonOwner",))
    body = json_body()
    v.require_object(body)

    salon_id = v.req_str(body, "salon_id")
    salon = get_salon(salon_id)

    name = v.req_str(body, "name")
    monthly_fee_cents = v.req_int(body, "monthly_fee_cents", minimum=0)
    service_discount_pct = v.req_number(body, "service_discount_pct", minimum=0, maximum=1)
    retail_discount_pct = v.opt_number(body, "retail_discount_pct", default=0.0, minimum=0, maximum=1)

    plan = {
        "salon_id": salon["id"],
        "name": name,
        "monthly_fee_cents": monthly_fee_cents,
        "service_discount_pct": service_discount_pct,
        "retail_discount_pct": retail_discount_pct,
    }
    stamp_create(plan)
    db.membership_plans[plan["id"]] = plan
    return success(public(plan), status=201)


@bp.get("/membership-plans/<plan_id>")
def get_plan(plan_id):
    auth(("SalonOwner", "FrontDesk", "Client"))
    plan = get_or_404(db.membership_plans, plan_id)
    return success(public(plan), status=200)


@bp.get("/membership-plans")
def list_plans():
    auth(("SalonOwner", "FrontDesk", "Client"))
    salon_id = request.args.get("salon_id")

    def pred(p):
        if salon_id is not None and p["salon_id"] != salon_id:
            return False
        return True

    page, meta = list_response(db.membership_plans, pred)
    return success(page, status=200, response_type="array", pagination=meta)
