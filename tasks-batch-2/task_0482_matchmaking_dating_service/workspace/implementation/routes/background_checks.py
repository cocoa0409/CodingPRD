from flask import Blueprint

import errors
from db import db, new_id
from middleware import authenticate, require_roles, require_member_owner
from response import success_object, success_array
from services.common import (
    get_json_body, require_str, require_enum, stamp_create, touch,
    parse_pagination, paginate, sort_by_created,
)
from services.compute import serialize_background_check, reconcile_member
from services.transitions import flag_background_cascade

bp = Blueprint("background_checks", __name__)

ALL_ROLES = ("BillingAdmin", "Matchmaker", "ScreeningOfficer", "Member")


def _get_member_or_404(member_id):
    m = db.members.get(member_id)
    if not m:
        raise errors.not_found("ERR_MEMBER_NOT_FOUND")
    return m


def _get_check_or_404(member_id, check_id):
    c = db.background_checks.get(check_id)
    if not c or c["member_id"] != member_id:
        raise errors.not_found("ERR_CHECK_NOT_FOUND")
    return c


def _plan_addon_for_member(member):
    mid = member.get("active_membership_id")
    if mid and mid in db.memberships:
        ms = db.memberships[mid]
        plan = db.membership_plans.get(ms["plan_id"])
        if plan:
            return plan["background_check_addon_cents"]
    return 0


@bp.route("/members/<member_id>/background-checks", methods=["POST"])
def order_check(member_id):
    principal = authenticate()
    require_roles(principal, ("ScreeningOfficer", "Member"))
    member = _get_member_or_404(member_id)
    require_member_owner(principal, member_id)
    body = get_json_body()
    provider_ref = require_str(body, "provider_ref")

    fee = _plan_addon_for_member(member)
    cid = new_id()
    check = {
        "id": cid,
        "member_id": member_id,
        "provider_ref": provider_ref,
        "fee_charged_cents": fee,
        "result": "NONE",
        "status": "ORDERED",
    }
    stamp_create(check)
    db.background_checks[cid] = check
    return success_object(serialize_background_check(check), 201)


@bp.route("/members/<member_id>/background-checks", methods=["GET"])
def list_checks(member_id):
    principal = authenticate()
    require_roles(principal, ALL_ROLES)
    _get_member_or_404(member_id)
    require_member_owner(principal, member_id)
    limit, offset = parse_pagination()
    records = [c for c in db.background_checks.values() if c["member_id"] == member_id]
    records = sort_by_created(records)
    page, total = paginate(records, limit, offset)
    return success_array([serialize_background_check(c) for c in page], limit, offset, total)


@bp.route("/members/<member_id>/background-checks/<check_id>/complete", methods=["POST"])
def complete_check(member_id, check_id):
    principal = authenticate()
    require_roles(principal, ("ScreeningOfficer",))
    member = _get_member_or_404(member_id)
    check = _get_check_or_404(member_id, check_id)
    body = get_json_body()
    result = require_enum(body, "result", ("CLEAR", "FLAGGED"))
    if check["status"] != "ORDERED":
        raise errors.conflict("ERR_CHECK_NOT_ORDERED")
    check["result"] = result
    check["status"] = "COMPLETED"
    touch(check)
    if result == "FLAGGED":
        flag_background_cascade(member)
    return success_object(serialize_background_check(check))


@bp.route("/members/<member_id>/background-checks/<check_id>/cancel", methods=["POST"])
def cancel_check(member_id, check_id):
    principal = authenticate()
    require_roles(principal, ("ScreeningOfficer",))
    member = _get_member_or_404(member_id)
    check = _get_check_or_404(member_id, check_id)
    if check["status"] != "ORDERED":
        raise errors.conflict("ERR_CHECK_NOT_ORDERED")
    check["status"] = "CANCELLED"
    touch(check)
    member["wallet_credit_cents"] = member.get("wallet_credit_cents", 0) + check["fee_charged_cents"]
    touch(member)
    return success_object(serialize_background_check(check))
