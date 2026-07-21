from flask import Blueprint

import core
from core import (
    db, ok, get_body, req_str, opt_enum, req_int, fetch,
    authenticate, authorize, new_common, touch, serialize, credit_wallet,
)

bp = Blueprint("members", __name__)

TIERS = {"BASIC", "PREMIER"}
STATUSES = {"ACTIVE", "LAPSED"}


@bp.route("/coop/members", methods=["POST"])
def create_member():
    # Registration is open (auth-exempt per PRD §2.1 / validation priority 1).
    data = get_body()
    email = req_str(data, "email")
    full_name = req_str(data, "full_name")
    tier = opt_enum(data, "membership_tier", TIERS, "BASIC")
    status = opt_enum(data, "membership_status", STATUSES, "ACTIVE")

    member = new_common()
    member.update({
        "email": email,
        "full_name": full_name,
        "membership_tier": tier,
        "membership_status": status,
        "store_credit_cents": 0,
        "loyalty_points_balance": 0,
        "lifetime_eligible_spend_cents": 0,
    })
    db.members[member["id"]] = member
    return ok(serialize(member), status=201)


@bp.route("/coop/members/<mid>", methods=["GET"])
def get_member(mid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    if role == "Member" and mid != uid:
        raise core.ApiError("ERR_UNAUTHORIZED", "Members may only read their own record")
    member = fetch("members", mid)
    return ok(serialize(member))


@bp.route("/coop/members/<mid>/store-credit", methods=["POST"])
def adjust_store_credit(mid):
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    data = get_body()
    amount = req_int(data, "amount_cents")
    # optional reason (free-form annotation)
    if "reason" in data and data["reason"] is not None and not isinstance(data["reason"], str):
        raise core.ApiError("ERR_VALIDATION", "'reason' must be a string")
    member = fetch("members", mid)
    credit_wallet(member, amount)  # signed; floored at 0; bumps version by 1
    return ok(serialize(member))
