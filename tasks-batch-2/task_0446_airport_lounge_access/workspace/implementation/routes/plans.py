"""MembershipPlan endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
from db import db, new_id, make_common_fields
from middleware import get_principal, require_role
from validation import get_json_body, require_enum, require_int
from serializers import serialize
from response import success
from routes.common import list_filtered

bp = Blueprint("plans", __name__)

CARD_STATUS = {"BASIC", "SILVER", "GOLD"}
TIERS = {"STANDARD", "PRESTIGE", "PRESTIGE_PLUS"}


@bp.route("/membership-plans", methods=["POST"])
def create_plan():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()

    tier = require_enum(body, "tier", TIERS)
    included_visits = require_int(body, "included_visits_per_year", minimum=-1)
    included_guest = require_int(body, "included_guest_visits_per_year", minimum=0)
    overage = require_int(body, "overage_charge_cents", minimum=0)
    guest_charge = require_int(body, "guest_charge_cents", minimum=0)
    min_card = require_enum(body, "min_card_status", CARD_STATUS)
    annual_fee = require_int(body, "annual_fee_cents", minimum=0)

    # tier unique across plans
    for p in db.membership_plans.items.values():
        if p["tier"] == tier:
            raise errors.invalid_request("tier must be unique across plans")

    plan = {
        "id": new_id(),
        "tier": tier,
        "included_visits_per_year": included_visits,
        "included_guest_visits_per_year": included_guest,
        "overage_charge_cents": overage,
        "guest_charge_cents": guest_charge,
        "min_card_status": min_card,
        "annual_fee_cents": annual_fee,
    }
    plan.update(make_common_fields())
    plan["_seq"] = db.membership_plans.next_seq()
    db.membership_plans.items[plan["id"]] = plan
    return success(serialize(plan), status=201)


@bp.route("/membership-plans", methods=["GET"])
def list_plans():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    return list_filtered(db.membership_plans, [("tier", "tier", "str")])


@bp.route("/membership-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    plan = db.membership_plans.items.get(plan_id)
    if not plan:
        raise errors.not_found("Plan not found")
    return success(serialize(plan))
