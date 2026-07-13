from flask import Blueprint

from db import db, new_row
from middleware import auth, body, must_exist, opt_bool, opt_enum, req_enum, req_int
from response import ok
from serializers import ser

bp = Blueprint("plans", __name__)

TIERS = ("STANDARD", "ADVANTAGE", "ULTIMATE")
BUREAU_SCOPES = ("SINGLE", "TRI")
SPECIALIST_TIERS = ("TIER1", "TIER2", "TIER3")


@bp.post("/idp/plans")
def create_plan():
    auth("PlatformAdmin")
    data = body()
    plan = new_row(
        tier=req_enum(data, "tier", TIERS),
        monthly_fee_cents=req_int(data, "monthly_fee_cents", minimum=0),
        insurance_limit_cents=req_int(data, "insurance_limit_cents", minimum=1),
        max_family_members=req_int(data, "max_family_members", minimum=0),
        child_monitoring_included=opt_bool(data, "child_monitoring_included", False),
        bureau_scope=req_enum(data, "bureau_scope", BUREAU_SCOPES),
        min_specialist_tier=opt_enum(data, "min_specialist_tier", SPECIALIST_TIERS, "TIER1"),
    )
    db.plans[plan["id"]] = plan
    return ok(ser(plan), 201)


@bp.get("/idp/plans/<plan_id>")
def read_plan(plan_id):
    auth("Anonymous", "Subscriber", "PlatformAdmin", "ClaimsAdjuster", "RestorationSpecialist")
    return ok(ser(must_exist("plans", plan_id)))
