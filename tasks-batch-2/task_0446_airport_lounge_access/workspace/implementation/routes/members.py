"""Member endpoints (PRD §3.2, §3.9)."""
from flask import Blueprint

import errors
import clock
import domain
from db import db, new_id, make_common_fields, touch
from middleware import get_principal, require_role
from validation import get_json_body, require_str
from serializers import serialize
from response import success
from routes.common import list_filtered

bp = Blueprint("members", __name__)


def _member_view(member):
    """Recompute derived counters before serializing a member read."""
    domain.recompute_member_usage(member)
    return serialize(member)


@bp.route("/memberships", methods=["POST"])
def enrol_member():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()

    plan_id = require_str(body, "plan_id")
    full_name = require_str(body, "full_name")
    if not domain.get_plan(plan_id):
        raise errors.not_found("Plan not found")

    member = {
        "id": new_id(),
        "plan_id": plan_id,
        "full_name": full_name,
        "membership_year_start": clock.now_iso_millis(),
        "visits_used": 0,
        "guest_visits_used": 0,
        "standing": "GOOD",
        "no_show_strikes": 0,
        "wallet_balance_cents": 0,
    }
    member.update(make_common_fields())
    member["_seq"] = db.members.next_seq()
    db.members.items[member["id"]] = member
    return success(serialize(member), status=201)


@bp.route("/memberships", methods=["GET"])
def list_members():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    # Recompute usage for each member before listing.
    for m in db.members.items.values():
        domain.recompute_member_usage(m)
    return list_filtered(
        db.members,
        [("plan_id", "plan_id", "str"), ("standing", "standing", "str")],
    )


@bp.route("/memberships/<member_id>", methods=["GET"])
def get_member(member_id):
    user_id, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member"})
    member = domain.get_member(member_id)
    if not member:
        raise errors.not_found("Member not found")
    if role == "Member" and user_id != member_id:
        raise errors.not_owner("Member may only read their own membership")
    return success(_member_view(member))


@bp.route("/memberships/<member_id>/reinstate", methods=["POST"])
def reinstate(member_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    member = domain.get_member(member_id)
    if not member:
        raise errors.not_found("Member not found")
    if member["standing"] != "SUSPENDED":
        raise errors.invalid_state("Member is not SUSPENDED")
    member["standing"] = "GOOD"
    member["no_show_strikes"] = 0
    touch(member)
    return success(serialize(member))


@bp.route("/memberships/<member_id>/roll-year", methods=["POST"])
def roll_year(member_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    member = domain.get_member(member_id)
    if not member:
        raise errors.not_found("Member not found")
    member["membership_year_start"] = clock.now_iso_millis()
    domain.recompute_member_usage(member)
    touch(member)
    return success(serialize(member))
