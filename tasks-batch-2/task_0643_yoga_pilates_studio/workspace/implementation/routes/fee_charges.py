"""FeeCharge endpoints: fetch, list, settle (PRD §3.7)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import authenticate, require_roles
from models import serialize, touch
from response import success, list_success
from helpers import (get_json_body, parse_pagination, paginate, find_or_404)

bp = Blueprint("fee_charges", __name__)


@bp.get("/fee-charges/<fid>")
def get_fee_charge(fid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    fee = find_or_404(store.fee_charges, fid, "FeeCharge")
    if principal.is_member and principal.user_id != fee["member_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only fetch their own fee charges")
    return success(serialize(fee))


@bp.get("/fee-charges")
def list_fee_charges():
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    limit, offset = parse_pagination()
    items = list(store.fee_charges.values())
    if principal.is_member:
        items = [f for f in items if f["member_id"] == principal.user_id]
    for key in ("member_id", "reservation_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [f for f in items if f.get(key) == val]
    window, total = paginate(items, limit, offset)
    return list_success([serialize(f) for f in window], 200, limit, offset, total)


@bp.post("/fee-charges/<fid>/settle")
def settle_fee_charge(fid):
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    fee = find_or_404(store.fee_charges, fid, "FeeCharge")
    body = get_json_body()
    resolution = body.get("resolution")
    if resolution not in ("PAID", "WAIVED"):
        raise err("ERR_INVALID_REQUEST", "resolution must be PAID or WAIVED")
    if fee["status"] != "UNPAID":
        raise err("ERR_FEE_ALREADY_RESOLVED", "Fee charge is already resolved")
    fee["status"] = resolution
    member = store.members.get(fee["member_id"])
    if member is not None:
        member["outstanding_fee_cents"] -= fee["amount_cents"]
        touch(member)
    # FeeCharge has no version/updated_at; status change is its lifecycle.
    return success(serialize(fee))
