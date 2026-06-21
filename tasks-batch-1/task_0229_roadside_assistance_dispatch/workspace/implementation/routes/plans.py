"""MembershipPlan routes (PRD §3.1)."""
from flask import Blueprint

import db
import errors
import serializers
import validation
from listing import sort_and_window
from middleware import authenticate, require_roles
from response import object_response, array_response

bp = Blueprint("plans", __name__)

VALID_SERVICE_TYPES = validation.SERVICE_TYPES


@bp.route("/membership-plans", methods=["POST"])
def create_plan():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    body = validation.get_body()

    validation.require_present(body, [
        "tier", "annual_service_limit", "per_incident_mileage_cap_miles",
        "overage_rate_cents_per_mile", "priority_weight", "covered_service_types",
        "base_service_fee_cents",
    ])

    tier = body["tier"]
    validation.require_enum(tier, {"BASIC", "PLUS", "PREMIER"}, "tier")
    # tier uniqueness
    for p in db.membership_plans.values():
        if p["tier"] == tier:
            raise errors.invalid_request("tier must be unique across plans.")

    annual_limit = body["annual_service_limit"]
    if not validation.is_int(annual_limit) or annual_limit < 1:
        raise errors.invalid_request("annual_service_limit must be an integer >= 1.")

    cap = body["per_incident_mileage_cap_miles"]
    if not validation.is_number(cap) or cap < 0:
        raise errors.invalid_request("per_incident_mileage_cap_miles must be >= 0.")

    rate = body["overage_rate_cents_per_mile"]
    if not validation.is_int(rate) or rate < 0:
        raise errors.invalid_request("overage_rate_cents_per_mile must be an integer >= 0.")

    weight = body["priority_weight"]
    if not validation.is_int(weight) or weight < 1:
        raise errors.invalid_request("priority_weight must be an integer >= 1.")

    covered = body["covered_service_types"]
    if (not isinstance(covered, list) or len(covered) == 0
            or any(c not in VALID_SERVICE_TYPES for c in covered)):
        raise errors.invalid_request(
            "covered_service_types must be a non-empty subset of service types.")

    base_fee = body["base_service_fee_cents"]
    if not validation.is_int(base_fee) or base_fee < 0:
        raise errors.invalid_request("base_service_fee_cents must be an integer >= 0.")

    record = {
        "tier": tier,
        "annual_service_limit": annual_limit,
        "per_incident_mileage_cap_miles": cap,
        "overage_rate_cents_per_mile": rate,
        "priority_weight": weight,
        "covered_service_types": list(covered),
        "base_service_fee_cents": base_fee,
    }
    db.stamp_create(record)
    db.membership_plans[record["id"]] = record
    return object_response(serializers.membership_plan(record), 201)


@bp.route("/membership-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "Member", "ServiceProvider"})
    plan = db.membership_plans.get(plan_id)
    if plan is None:
        raise errors.not_found("Plan not found.")
    return object_response(serializers.membership_plan(plan), 200)


@bp.route("/membership-plans", methods=["GET"])
def list_plans():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "Member", "ServiceProvider"})
    from flask import request
    limit, offset = validation.parse_pagination()
    tier = request.args.get("tier")
    records = list(db.membership_plans.values())
    if tier is not None:
        records = [p for p in records if p["tier"] == tier]
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.membership_plan(p) for p in page],
                          limit, offset, total, 200)
