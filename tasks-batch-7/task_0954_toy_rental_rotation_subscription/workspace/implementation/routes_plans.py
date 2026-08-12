"""Subscription plan routes."""
from flask import Blueprint

from domain import base_fields, by_seq
from envelope import ok_list, ok_object
from errors import not_found
from serializers import serialize_plan, serialize_subscription
from store import DB
from validate import (
    F,
    authenticate,
    authorize,
    body,
    finalize_shape,
    paginate,
    parse_fields,
)

bp = Blueprint("plans", __name__)


def _get_plan(pid):
    p = DB.plans.get(pid)
    if p is None:
        raise not_found("ERR_PLAN_NOT_FOUND", "SubscriptionPlan id does not exist.")
    return p


@bp.post("/toy-rental/subscription-plans")
def create_plan():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    data = body()
    shape = parse_fields(data, [
        F("name", True, "str"),
        F("monthly_fee_cents", True, "int", min=0),
        F("toys_per_box", True, "int", min=1),
        F("swap_allowance_per_cycle", True, "int", min=0),
        F("max_holds", True, "int", min=0),
        F("rotation_cadence_days", True, "int", min=1),
        F("rental_period_days", True, "int", min=1),
        F("buyout_discount_pct", True, "number", min=0, max=1, hi_exclusive=True),
    ])
    finalize_shape(shape)
    p = base_fields()
    p.update({k: shape.values[k] for k in (
        "name", "monthly_fee_cents", "toys_per_box", "swap_allowance_per_cycle",
        "max_holds", "rotation_cadence_days", "rental_period_days",
        "buyout_discount_pct")})
    DB.plans[p["id"]] = p
    return ok_object(serialize_plan(p), status=201)


@bp.get("/toy-rental/subscription-plans")
def list_plans():
    uid, role = authenticate()
    authorize(role, {"Member", "CustomerService", "PlatformAdmin"})
    plans = by_seq(DB.plans.values())
    page, meta = paginate(plans)
    return ok_list([serialize_plan(p) for p in page], meta)


@bp.get("/toy-rental/subscription-plans/<pid>")
def get_plan(pid):
    uid, role = authenticate()
    authorize(role, {"Member", "CustomerService", "PlatformAdmin"})
    p = _get_plan(pid)
    return ok_object(serialize_plan(p))


@bp.get("/toy-rental/subscription-plans/<pid>/subscriptions")
def list_plan_subscriptions(pid):
    uid, role = authenticate()
    authorize(role, {"CustomerService", "PlatformAdmin"})
    p = _get_plan(pid)
    subs = by_seq([s for s in DB.subscriptions.values() if s["plan_id"] == pid])
    page, meta = paginate(subs)
    return ok_list([serialize_subscription(s) for s in page], meta)
