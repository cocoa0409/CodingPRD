"""Test-driving capabilities (PRD §3.2, §3.10)."""
from flask import Blueprint, request

import db
import lookup
import serialize
import util
from errors import err
from middleware import get_principal, require_roles
from response import object_response
from services import calc, loyalty

bp = Blueprint("testdrive", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent"})
    body = request.get_json(silent=True) or {}

    to_iso = util.require_str(body, "to_iso8601")
    dt = util.parse_iso8601(to_iso)
    db.set_current_utc(dt)
    return object_response({}, 200)


@bp.route("/_members/<member_id>/set_loyalty", methods=["POST"])
def set_loyalty(member_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent"})
    member = lookup.get_member(member_id)
    body = request.get_json(silent=True) or {}

    if "lifetime_points" in body and body["lifetime_points"] is not None:
        member["_lifetime_override"] = util.optional_int(body, "lifetime_points")
    if "points_balance" in body and body["points_balance"] is not None:
        member["_balance_override"] = util.optional_int(body, "points_balance")
    if "no_show_strikes" in body and body["no_show_strikes"] is not None:
        member["_strikes_override"] = util.optional_int(body, "no_show_strikes")

    # tier: explicit override wins, else recompute from lifetime points.
    if "tier" in body and body["tier"] is not None:
        tier = body["tier"]
        if tier not in ("STANDARD", "SILVER", "GOLD"):
            raise err("ERR_INVALID_REQUEST", "invalid tier: %s" % tier)
        member["tier"] = tier
    else:
        if member.get("_lifetime_override") is not None:
            lifetime = member["_lifetime_override"]
        else:
            _, lifetime = serialize.member_points(member_id)
        member["tier"] = calc.member_tier(lifetime)

    util.touch(member)
    return object_response(serialize.member(member), 200)
