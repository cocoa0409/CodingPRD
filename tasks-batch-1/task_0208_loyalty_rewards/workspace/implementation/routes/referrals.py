"""Referrals: create, get, list, member-scoped list, revoke. (PRD §3.6)"""
from flask import Blueprint, request

from db import db
from errors import (err, ERR_SELF_REFERRAL, ERR_REFEREE_EXISTS,
                    ERR_INVALID_STATE)
from middleware import require_roles
from response import success
from services import serialize
from services.helpers import get_json_body, require_str, paginate
from services.lookup import (get_program, get_member, get_referral,
                             assert_member_owner)

bp = Blueprint("referrals", __name__)


@bp.post("/referrals")
def create_referral():
    _, role = require_roles("ProgramAdmin", "Member")
    body = get_json_body()
    program_id = require_str(body, "program_id")
    referrer_member_id = require_str(body, "referrer_member_id")
    referee_email = require_str(body, "referee_email")

    get_program(program_id)
    referrer = get_member(referrer_member_id)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, referrer_member_id)

    # self-referral first (priority 23)
    if referee_email == referrer["email"]:
        raise err(ERR_SELF_REFERRAL, "Cannot refer yourself")
    # referee already enrolled (priority 24)
    for m in db.members.values():
        if m["program_id"] == program_id and m["email"] == referee_email:
            raise err(ERR_REFEREE_EXISTS, "Referee email already registered")

    ref = {
        "program_id": program_id,
        "referrer_member_id": referrer_member_id,
        "referee_member_id": None,
        "referee_email": referee_email,
        "status": "PENDING",
        "completed_at": None,
    }
    db.stamp_create(ref)
    db.referrals[ref["id"]] = ref
    return success(serialize.referral_out(ref), 201)


@bp.get("/referrals/<rid>")
def get_referral_route(rid):
    _, role = require_roles("ProgramAdmin", "Member")
    ref = get_referral(rid)
    if role == "Member":
        user_id = request.headers.get("X-User-ID")
        if user_id not in (ref["referrer_member_id"], ref["referee_member_id"]):
            from errors import ERR_NOT_RESOURCE_OWNER
            raise err(ERR_NOT_RESOURCE_OWNER, "Member does not own this referral")
    return success(serialize.referral_out(ref), 200)


@bp.get("/referrals")
def list_referrals():
    require_roles("ProgramAdmin")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(db.referrals.values())
    if program_id is not None:
        items = [r for r in items if r["program_id"] == program_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pg = paginate(items)
    return success([serialize.referral_out(x) for x in page], 200, pg)


@bp.get("/members/<mid>/referrals")
def list_member_referrals(mid):
    _, role = require_roles("ProgramAdmin", "Member")
    get_member(mid)
    user_id = request.headers.get("X-User-ID")
    assert_member_owner(role, user_id, mid)
    role_filter = request.args.get("role")   # 'referrer' | 'referee'
    status = request.args.get("status")

    items = []
    for r in db.referrals.values():
        is_referrer = r["referrer_member_id"] == mid
        is_referee = r["referee_member_id"] == mid
        if role_filter == "referrer":
            keep = is_referrer
        elif role_filter == "referee":
            keep = is_referee
        else:
            keep = is_referrer or is_referee
        if keep:
            items.append(r)
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pg = paginate(items)
    return success([serialize.referral_out(x) for x in page], 200, pg)


@bp.post("/referrals/<rid>/revoke")
def revoke_referral(rid):
    require_roles("ProgramAdmin")
    ref = get_referral(rid)
    if ref["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "Referral is not PENDING")
    ref["status"] = "REVOKED"
    db.touch(ref)
    return success(serialize.referral_out(ref), 200)
