"""Member routes (PRD §3.2)."""
from flask import Blueprint, request

import clock
import db
import errors
import serializers
import validation
from listing import sort_and_window
from middleware import authenticate, require_roles
from response import object_response, array_response

bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def create_member():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    body = validation.get_body()

    validation.require_present(body, ["plan_id", "full_name", "home_lat", "home_lng"])

    plan_id = body["plan_id"]
    if not isinstance(plan_id, str):
        raise errors.invalid_request("plan_id must be a string.")
    # existence (FK) — checked at existence priority via not_found
    plan = db.membership_plans.get(plan_id)
    if plan is None:
        raise errors.not_found("Plan not found.")

    validation.require_str(body["full_name"], "full_name")
    validation.require_lat(body["home_lat"], "home_lat")
    validation.require_lng(body["home_lng"], "home_lng")

    now_iso = clock.now_iso()
    record = {
        "plan_id": plan_id,
        "full_name": body["full_name"],
        "status": "ACTIVE",
        "home_lat": body["home_lat"],
        "home_lng": body["home_lng"],
        "annual_period_start": now_iso,
        "services_used_this_year": 0,
        "outstanding_balance_cents": 0,
    }
    db.stamp_create(record)
    # annual_period_start must equal created_at
    record["annual_period_start"] = record["created_at"]
    db.members[record["id"]] = record
    return object_response(serializers.member(record), 201)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "Member"})
    m = db.members.get(member_id)
    if m is None:
        raise errors.not_found("Member not found.")
    if ident.is_member and ident.user_id != member_id:
        raise errors.not_resource_owner("A member may only fetch its own record.")
    return object_response(serializers.member(m), 200)


@bp.route("/members", methods=["GET"])
def list_members():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    limit, offset = validation.parse_pagination()
    plan_id = request.args.get("plan_id")
    status = request.args.get("status")
    records = list(db.members.values())
    if plan_id is not None:
        records = [m for m in records if m["plan_id"] == plan_id]
    if status is not None:
        records = [m for m in records if m["status"] == status]
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.member(m) for m in page],
                          limit, offset, total, 200)


@bp.route("/members/<member_id>/suspend", methods=["POST"])
def suspend_member(member_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    m = db.members.get(member_id)
    if m is None:
        raise errors.not_found("Member not found.")
    if m["status"] != "ACTIVE":
        raise errors.invalid_state("Member must be ACTIVE to suspend.")
    m["status"] = "SUSPENDED"
    db.touch(m)
    return object_response(serializers.member(m), 200)


@bp.route("/members/<member_id>/reinstate", methods=["POST"])
def reinstate_member(member_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    m = db.members.get(member_id)
    if m is None:
        raise errors.not_found("Member not found.")
    if m["status"] != "SUSPENDED":
        raise errors.invalid_state("Member must be SUSPENDED to reinstate.")
    m["status"] = "ACTIVE"
    db.touch(m)
    return object_response(serializers.member(m), 200)
