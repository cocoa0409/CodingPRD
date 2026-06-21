"""LoyaltyMember endpoints (PRD §3.2)."""
from flask import Blueprint, request

import db
import lookup
import serialize
import util
from errors import err
from middleware import get_principal, require_roles
from pagination import paginate
from response import array_response, object_response

bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def register_member():
    user_id, role = get_principal()
    require_roles(role, {"RentalAgent", "Member"})
    body = request.get_json(silent=True) or {}

    email = util.require_str(body, "email")
    full_name = util.require_str(body, "full_name")
    driver_age = util.require_int(body, "driver_age", minimum=18)

    for existing in db.members.values():
        if existing["email"] == email:
            raise err("ERR_INVALID_REQUEST", "member email already exists: %s" % email)

    rec = util.stamp_new(
        {
            "email": email,
            "full_name": full_name,
            "driver_age": driver_age,
            "tier": "STANDARD",
            "_lifetime_override": None,
            "_balance_override": None,
            "_strikes_override": None,
        }
    )
    db.members[rec["id"]] = rec
    return object_response(serialize.member(rec), 201)


def _enforce_member_ownership(user_id, role, member_id):
    """A Member may only act on/read their own account."""
    if role == "Member" and user_id != member_id:
        raise err("ERR_FORBIDDEN", "members may only act on their own account")


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    user_id, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    rec = lookup.get_member(member_id)
    _enforce_member_ownership(user_id, role, member_id)
    return object_response(serialize.member(rec), 200)


@bp.route("/members/<member_id>/reservations", methods=["GET"])
def list_member_reservations(member_id):
    user_id, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    lookup.get_member(member_id)
    _enforce_member_ownership(user_id, role, member_id)

    status = request.args.get("status")
    matches = [
        r
        for r in db.reservations.values()
        if r["member_id"] == member_id and (status is None or r["status"] == status)
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.reservation(r) for r in page], limit, offset, total, 200
    )


@bp.route("/members/<member_id>/loyalty-accruals", methods=["GET"])
def list_member_accruals(member_id):
    user_id, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    lookup.get_member(member_id)
    _enforce_member_ownership(user_id, role, member_id)

    kind = request.args.get("kind")
    matches = [
        a
        for a in db.loyalty_accruals.values()
        if a["member_id"] == member_id and (kind is None or a["kind"] == kind)
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.loyalty_accrual(a) for a in page], limit, offset, total, 200
    )


@bp.route("/members/<member_id>/redeem", methods=["POST"])
def redeem_points(member_id):
    user_id, role = get_principal()
    require_roles(role, {"RentalAgent", "Member"})
    member = lookup.get_member(member_id)
    _enforce_member_ownership(user_id, role, member_id)
    body = request.get_json(silent=True) or {}

    points = util.require_int(body, "points", minimum=0)

    # points_balance: honor override if pinned, else derive.
    if member.get("_balance_override") is not None:
        balance = member["_balance_override"]
    else:
        balance, _ = serialize.member_points(member_id)

    if points > balance:
        raise err(
            "ERR_INSUFFICIENT_POINTS",
            "redemption %s exceeds balance %s" % (points, balance),
        )

    accrual = util.stamp_audit(
        {
            "member_id": member_id,
            "agreement_id": None,
            "kind": "REDEMPTION",
            "delta_points": -points,
        }
    )
    db.loyalty_accruals[accrual["id"]] = accrual

    # points_balance recomputed (cascade): if it was pinned, drop the override
    # toward the now-history-derived value so the redemption is observable.
    if member.get("_balance_override") is not None:
        member["_balance_override"] = member["_balance_override"] - points
    util.touch(member)
    return object_response(serialize.loyalty_accrual(accrual), 201)
