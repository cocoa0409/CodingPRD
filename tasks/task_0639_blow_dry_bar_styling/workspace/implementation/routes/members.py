"""Member routes: register, list, get, prepay top-up, reinstate."""

from flask import Blueprint, request

import errors
from common import (
    as_int, as_str, get_json_body, paginate, sort_by_created, stamp_new, touch,
)
from db import db
from errors import err
from lookup import get_member, get_membership_plan
from middleware import get_auth, require_role
from response import success_list, success_object
from serialize import public, public_list
from services.reconcile import reconcile_member

bp = Blueprint("members", __name__)


@bp.post("/members")
def create_member():
    user_id, role = get_auth()
    require_role(role, {"FrontDesk"})
    body = get_json_body()
    full_name = as_str(body, "full_name")
    email = as_str(body, "email")
    plan_id = body.get("membership_plan_id")
    # email unique across members
    for m in db.members.values():
        if m["email"] == email:
            raise err(errors.ERR_INVALID_REQUEST, "email must be unique across members")
    # validate plan existence if supplied (FK existence, §2.7)
    plan = None
    if plan_id is not None:
        plan = get_membership_plan(plan_id)
        if plan is None:
            raise err(errors.ERR_MEMBER_NOT_FOUND, "membership_plan_id does not exist")
    seeded_credits = plan["included_blowout_credits"] if plan is not None else 0
    member = stamp_new({
        "full_name": full_name,
        "email": email,
        "membership_plan_id": plan_id,
        "blowout_credit_balance": seeded_credits,
        "prepay_balance_cents": 0,
        "no_show_strikes": 0,
        "status": "ACTIVE",
        "_reinstate_resets": 0,
    })
    db.members[member["id"]] = member
    return success_object(public(member), 201)


@bp.get("/members")
def list_members():
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager"})
    items = list(db.members.values())
    plan_id = request.args.get("membership_plan_id")
    if plan_id is not None:
        items = [m for m in items if m.get("membership_plan_id") == plan_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/members/<mid>")
def get_one_member(mid):
    user_id, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager", "Member"})
    member = get_member(mid)
    if role == "Member" and user_id != member["id"]:
        raise err(errors.ERR_NOT_OWNER, "Member may only read their own record")
    return success_object(public(member), 200)


@bp.post("/members/<mid>/prepay")
def prepay(mid):
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager"})
    member = get_member(mid)
    body = get_json_body()
    amount = as_int(body, "amount_cents")
    if amount < 0:
        raise err(errors.ERR_INVALID_REQUEST, "amount_cents must be >= 0")
    db.prepay_topups.append({"member_id": member["id"], "amount_cents": amount})
    reconcile_member(member)
    touch(member)
    return success_object(public(member), 200)


@bp.post("/members/<mid>/reinstate")
def reinstate(mid):
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    member = get_member(mid)
    body = get_json_body()
    expected_version = as_int(body, "expected_member_version")
    if member["status"] != "SUSPENDED":
        raise err(errors.ERR_MEMBER_NOT_SUSPENDED, "Member is not SUSPENDED")
    if expected_version != member["version"]:
        raise err(errors.ERR_STALE_VERSION, "expected_member_version does not match current version")
    # Reset strikes: record reinstate resets equal to current no-show appointment count.
    member["_reinstate_resets"] = sum(
        1 for a in db.appointments.values()
        if a["member_id"] == member["id"]
        and a["lifecycle_status"] == "NO_SHOW" and a.get("arrival_status") == "NO_SHOW"
    )
    member["no_show_strikes"] = 0
    member["status"] = "ACTIVE"
    touch(member)
    return success_object(public(member), 200)
