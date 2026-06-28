"""Membership routes & lifecycle (PRD §3.3)."""
from flask import Blueprint

import errors
from errors import err
from db import db
from response import success
from serialize import out
from middleware import get_auth, require_role
from validators import get_body, require_int, parse_pagination
from services import lookup
from routes.common import arg, paginate

bp = Blueprint("memberships", __name__)


@bp.route("/memberships", methods=["POST"])
def create_membership():
    user_id, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    body = get_body()
    member_id = body.get("member_id")
    # ownership (priority 3) before existence comparison: resolve member.
    member = lookup.require_member(member_id)
    lookup.check_owner(role, user_id, lookup.member_guardian_id(member))
    monthly_fee = require_int(body, "monthly_fee_cents", minimum=0)
    included = require_int(body, "included_sessions_per_cycle", minimum=0)
    rec = db.make({
        "member_id": member_id,
        "monthly_fee_cents": monthly_fee,
        "included_sessions_per_cycle": included,
        "sessions_used_this_cycle": 0,
        "status": "PENDING",
        "cycle_index": 0,
    })
    db.memberships[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/memberships/<rid>", methods=["GET"])
def get_membership(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    rec = lookup.require_membership(rid)
    return success(out(rec))


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    limit, offset = parse_pagination()
    member_id = arg("member_id")
    items = [m for m in db.memberships.values()
             if member_id is None or m["member_id"] == member_id]
    return paginate(items, limit, offset)


def _owner_check(role, user_id, membership):
    gid = lookup.membership_guardian_id(membership)
    lookup.check_owner(role, user_id, gid)


@bp.route("/memberships/<rid>/activate", methods=["POST"])
def activate_membership(rid):
    user_id, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    m = lookup.require_membership(rid)
    _owner_check(role, user_id, m)
    if m["status"] != "PENDING":
        raise err(errors.ERR_INVALID_STATE, "Membership is not PENDING.")
    m["status"] = "ACTIVE"
    m["sessions_used_this_cycle"] = 0
    m["cycle_index"] = 0
    db.touch(m)
    return success(out(m))


@bp.route("/memberships/<rid>/pause", methods=["POST"])
def pause_membership(rid):
    user_id, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    m = lookup.require_membership(rid)
    _owner_check(role, user_id, m)
    if m["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Membership is not ACTIVE.")
    m["status"] = "PAUSED"
    db.touch(m)
    return success(out(m))


@bp.route("/memberships/<rid>/resume", methods=["POST"])
def resume_membership(rid):
    user_id, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    m = lookup.require_membership(rid)
    _owner_check(role, user_id, m)
    if m["status"] != "PAUSED":
        raise err(errors.ERR_INVALID_STATE, "Membership is not PAUSED.")
    m["status"] = "ACTIVE"
    db.touch(m)
    return success(out(m))


@bp.route("/memberships/<rid>/cancel", methods=["POST"])
def cancel_membership(rid):
    user_id, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    m = lookup.require_membership(rid)
    _owner_check(role, user_id, m)
    if m["status"] not in ("ACTIVE", "PAUSED"):
        raise err(errors.ERR_INVALID_STATE, "Membership cannot be cancelled from its current state.")
    m["status"] = "CANCELLED"
    db.touch(m)
    return success(out(m))
