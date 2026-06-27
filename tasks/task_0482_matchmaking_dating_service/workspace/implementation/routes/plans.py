from flask import Blueprint, request

import errors
from db import db, new_id
from middleware import authenticate, require_roles
from response import success_object, success_array
from services.common import (
    get_json_body, require_enum, require_int, opt_bool, stamp_create, touch,
    parse_pagination, paginate, sort_by_created,
)
from services.compute import serialize_plan, serialize_membership, reconcile_membership

bp = Blueprint("plans", __name__)

ALL_ROLES = ("BillingAdmin", "Matchmaker", "ScreeningOfficer", "Member")
OPERATOR_ROLES = ("BillingAdmin", "Matchmaker", "ScreeningOfficer")
TIERS = ("BASIC", "PLUS", "ELITE")


@bp.route("/membership-plans", methods=["POST"])
def create_plan():
    principal = authenticate()
    require_roles(principal, ("BillingAdmin",))
    body = get_json_body()
    tier = require_enum(body, "tier", TIERS)
    monthly_fee_cents = require_int(body, "monthly_fee_cents")
    term_months = require_int(body, "term_months")
    guaranteed = require_int(body, "guaranteed_introductions")
    included = require_int(body, "included_coaching_sessions")
    coaching_value = require_int(body, "coaching_value_cents")
    bg_addon = require_int(body, "background_check_addon_cents")
    priority = opt_bool(body, "priority_match_enabled", False)

    if monthly_fee_cents < 0 or term_months < 1 or guaranteed < 0 or included < 0 \
            or coaching_value < 0 or bg_addon < 0:
        raise errors.invalid_request("Numeric plan fields out of range.")

    # tier unique among non-archived plans
    for p in db.membership_plans.values():
        if p["tier"] == tier and not p["archived"]:
            raise errors.invalid_request(f"Tier {tier} already exists among active plans.")

    pid = new_id()
    plan = {
        "id": pid,
        "tier": tier,
        "monthly_fee_cents": monthly_fee_cents,
        "term_months": term_months,
        "guaranteed_introductions": guaranteed,
        "priority_match_enabled": priority,
        "included_coaching_sessions": included,
        "coaching_value_cents": coaching_value,
        "background_check_addon_cents": bg_addon,
        "archived": False,
        "status": "ACTIVE",
    }
    stamp_create(plan)
    db.membership_plans[pid] = plan
    return success_object(serialize_plan(plan), 201)


@bp.route("/membership-plans", methods=["GET"])
def list_plans():
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    include_archived = request.args.get("include_archived", "false").lower() == "true"
    limit, offset = parse_pagination()
    records = [p for p in db.membership_plans.values() if include_archived or not p["archived"]]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_plan(p) for p in page], limit, offset, total)


@bp.route("/membership-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    plan = db.membership_plans.get(plan_id)
    if not plan:
        raise errors.not_found("ERR_PLAN_NOT_FOUND")
    return success_object(serialize_plan(plan))


@bp.route("/membership-plans/<plan_id>/archive", methods=["POST"])
def archive_plan(plan_id):
    principal = authenticate()
    require_roles(principal, ("BillingAdmin",))
    plan = db.membership_plans.get(plan_id)
    if not plan:
        raise errors.not_found("ERR_PLAN_NOT_FOUND")
    plan["archived"] = True
    plan["status"] = "ARCHIVED"
    touch(plan)
    return success_object(serialize_plan(plan))


@bp.route("/membership-plans/<plan_id>/memberships", methods=["GET"])
def list_plan_memberships(plan_id):
    principal = authenticate()
    require_roles(principal, OPERATOR_ROLES)
    plan = db.membership_plans.get(plan_id)
    if not plan:
        raise errors.not_found("ERR_PLAN_NOT_FOUND")
    limit, offset = parse_pagination()
    records = [m for m in db.memberships.values() if m["plan_id"] == plan_id]
    for m in records:
        reconcile_membership(m)
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_membership(m) for m in page], limit, offset, total)
