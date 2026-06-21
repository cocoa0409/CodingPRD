"""SubscriptionPlan (catalog) routes."""

from flask import Blueprint

import constants
import validators
from common import base_entity, get_or_404, serialize
from db import store
from middleware import get_json_body, roles
from response import object_response

bp = Blueprint("plans", __name__)


@bp.route("/legal/subscription-plans", methods=["POST"])
@roles("PlatformAdmin")
def create_plan():
    body = get_json_body()
    tier = validators.require_enum(body, "tier", constants.TIERS)
    monthly_fee = validators.require_int(body, "monthly_fee_cents", minimum=0)
    credits = validators.require_int(body, "included_project_credits", minimum=0)
    clause_count = validators.require_int(body, "included_clause_count", minimum=0)
    sub_discount = validators.require_number(body, "subscription_discount_pct", minimum=0.0, maximum=1.0)
    review_discount = validators.require_number(body, "review_discount_pct", minimum=0.0, maximum=1.0)

    ent = base_entity()
    ent.update({
        "tier": tier,
        "monthly_fee_cents": monthly_fee,
        "included_project_credits": credits,
        "included_clause_count": clause_count,
        "subscription_discount_pct": sub_discount,
        "review_discount_pct": review_discount,
    })
    store.subscription_plans[ent["id"]] = ent
    return object_response(serialize(ent), 201)


@bp.route("/legal/subscription-plans/<pid>", methods=["GET"])
@roles("Customer", "Attorney", "PlatformAdmin")
def get_plan(pid):
    ent = get_or_404(store.subscription_plans, pid)
    return object_response(serialize(ent), 200)
