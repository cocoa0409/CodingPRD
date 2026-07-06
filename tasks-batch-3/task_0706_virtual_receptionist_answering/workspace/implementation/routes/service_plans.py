"""ServicePlan routes (PRD §3.1)."""
from flask import Blueprint

import errors
import serializers
from db import db
from response import success_object, success_array
from middleware import get_auth, require_role, ROLE_ADMIN, ROLE_OWNER
from common import (get_body, make_record, paginate, public,
                    as_str, as_int, as_enum)
from services.lookups import find_or_404

bp = Blueprint("service_plans", __name__)

BILLING_MODELS = {"PER_MINUTE", "PER_CALL"}
MINUTE_ROUNDINGS = {"CEIL_MINUTE"}


@bp.route("/va/service-plans", methods=["POST"])
def create_plan():
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN})
    body = get_body()

    name = as_str(body, "name", required=True)
    billing_model = as_enum(body, "billing_model", BILLING_MODELS, required=True)
    base_fee_cents = as_int(body, "base_fee_cents", required=True, minimum=0)
    overage_rate_cents = as_int(body, "overage_rate_cents", required=True, minimum=0)
    overage_tier2_rate_cents = as_int(body, "overage_tier2_rate_cents", required=True, minimum=0)
    hard_cap_overage_cents = as_int(body, "hard_cap_overage_cents", required=True)
    included_minutes = as_int(body, "included_minutes", default=0, minimum=0)
    included_calls = as_int(body, "included_calls", default=0, minimum=0)
    overage_tier2_threshold = as_int(body, "overage_tier2_threshold", default=100, minimum=1)
    minute_rounding = as_enum(body, "minute_rounding", MINUTE_ROUNDINGS, default="CEIL_MINUTE")

    # ERR_PLAN_MISCONFIGURED (PRD §3.1): mismatched allowance for the model, or
    # hard_cap < 1.
    if hard_cap_overage_cents < 1:
        raise errors.err(errors.ERR_PLAN_MISCONFIGURED, "hard_cap_overage_cents must be >= 1")
    if billing_model == "PER_MINUTE" and included_calls > 0:
        raise errors.err(errors.ERR_PLAN_MISCONFIGURED, "PER_MINUTE plan cannot declare included_calls")
    if billing_model == "PER_CALL" and included_minutes > 0:
        raise errors.err(errors.ERR_PLAN_MISCONFIGURED, "PER_CALL plan cannot declare included_minutes")

    rec = make_record({
        "name": name,
        "billing_model": billing_model,
        "included_minutes": included_minutes,
        "included_calls": included_calls,
        "base_fee_cents": base_fee_cents,
        "overage_rate_cents": overage_rate_cents,
        "overage_tier2_threshold": overage_tier2_threshold,
        "overage_tier2_rate_cents": overage_tier2_rate_cents,
        "hard_cap_overage_cents": hard_cap_overage_cents,
        "minute_rounding": minute_rounding,
    }, common_fields=False)
    db.service_plans[rec["id"]] = rec
    return success_object(serializers.service_plan(public(rec)), 201)


@bp.route("/va/service-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    rec = find_or_404(db.service_plans, plan_id)
    return success_object(serializers.service_plan(public(rec)), 200)


@bp.route("/va/service-plans", methods=["GET"])
def list_plans():
    _, role = get_auth()
    require_role(role, {ROLE_ADMIN, ROLE_OWNER})
    records = list(db.service_plans.values())
    page, meta = paginate(records)
    return success_array([serializers.service_plan(public(r)) for r in page], meta, 200)
