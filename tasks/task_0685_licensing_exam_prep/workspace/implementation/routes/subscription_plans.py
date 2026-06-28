"""SubscriptionPlan routes (PRD §3.1)."""
from flask import Blueprint

from db import db, stamp_create, touch
from response import success
from middleware import get_auth, require_role
from services import validate as V
from services.serialize import public
from services.lookups import get_subscription_plan
from errors import raise_err
import errors

bp = Blueprint("subscription_plans", __name__)


@bp.post("/subscription-plans")
def create_plan():
    _, role = get_auth()
    require_role(role, {"ContentAdmin"})
    data = V.body()
    tier = V.as_enum(V.require(data, "tier"), "tier", {"BASIC", "PLUS", "PRO"})
    total_price_cents = V.as_int(V.require(data, "total_price_cents"),
                                 "total_price_cents", minimum=0)
    down_payment_pct = V.as_number(V.require(data, "down_payment_pct"),
                                   "down_payment_pct", minimum=0.0, maximum=1.0)
    financing_months = V.as_int(V.require(data, "financing_months"),
                                "financing_months", minimum=1, maximum=24)
    included_mock_credits = V.as_int(V.require(data, "included_mock_credits"),
                                     "included_mock_credits", minimum=0)
    pass_guarantee = V.as_bool(V.opt(data, "pass_guarantee", False), "pass_guarantee")
    guarantee_refund_pct = V.as_number(V.opt(data, "guarantee_refund_pct", 0.0),
                                       "guarantee_refund_pct", minimum=0.0, maximum=1.0)
    includes_ce = V.as_bool(V.opt(data, "includes_ce", False), "includes_ce")
    rec = {
        "tier": tier,
        "total_price_cents": total_price_cents,
        "down_payment_pct": down_payment_pct,
        "financing_months": financing_months,
        "included_mock_credits": included_mock_credits,
        "pass_guarantee": pass_guarantee,
        "guarantee_refund_pct": guarantee_refund_pct,
        "includes_ce": includes_ce,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.subscription_plans[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/subscription-plans/<pid>")
def get_plan(pid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin", "Learner"})
    rec = get_subscription_plan(pid)
    return success(public(rec))


@bp.post("/subscription-plans/<pid>/archive")
def archive_plan(pid):
    _, role = get_auth()
    require_role(role, {"ContentAdmin"})
    rec = get_subscription_plan(pid)
    if rec["status"] != "ACTIVE":
        raise_err(errors.ERR_INVALID_STATE, "plan not ACTIVE")
    rec["status"] = "ARCHIVED"
    touch(rec)
    return success(public(rec))
