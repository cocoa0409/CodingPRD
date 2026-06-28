"""CreditPack routes: purchase (tiered pricing), list, get (PRD §3.8)."""
from flask import Blueprint, request

from db import store
from errors import err, ERR_NOT_FOUND
from middleware import authenticate, require_role, forbid
from response import success, success_list
from util import (
    get_json_body, require_str, require_int, parse_pagination, paginate, parse_iso,
)
from services.common import make_full
from services.calc import credit_pack_price
from services import serialize

bp = Blueprint("credit_packs", __name__)

MEMBER_ROLES = ["StudioManager", "FrontDesk", "Member"]


@bp.route("/credit-packs", methods=["POST"])
def create_credit_pack():
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    body = get_json_body()
    member_id = require_str(body, "member_id")
    location_id = require_str(body, "location_id")
    pack_credits = require_int(body, "pack_credits", minimum=1)
    base_unit_price = require_int(body, "base_unit_price_cents", minimum=0)
    expires_utc = require_str(body, "expires_utc")
    parse_iso(expires_utc)  # validate format

    if p.is_member and p.user_id != member_id:
        forbid()
    if member_id not in store.members:
        raise err(ERR_NOT_FOUND, "Member not found.")
    if location_id not in store.locations:
        raise err(ERR_NOT_FOUND, "Location not found.")

    price = credit_pack_price(base_unit_price, pack_credits)
    rec = make_full({
        "member_id": member_id,
        "location_id": location_id,
        "pack_credits": pack_credits,
        "base_unit_price_cents": base_unit_price,
        "price_cents": price,
        "expires_utc": expires_utc,
        "status": "ACTIVE",
    })
    store.credit_packs[rec["id"]] = rec
    return success(serialize.creditpack_view(rec), 201)


@bp.route("/credit-packs", methods=["GET"])
def list_credit_packs():
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    limit, offset = parse_pagination()
    member_id = _qs("member_id")
    location_id = _qs("location_id")
    status = _qs("status")
    items = [r for r in store.credit_packs.values()
             if (member_id is None or r["member_id"] == member_id)
             and (location_id is None or r["location_id"] == location_id)
             and (status is None or r["status"] == status)]
    if p.is_member:
        items = [r for r in items if r["member_id"] == p.user_id]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.creditpack_view(r) for r in window], limit, offset, total)


@bp.route("/credit-packs/<cid>", methods=["GET"])
def get_credit_pack(cid):
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    rec = store.credit_packs.get(cid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Credit pack not found.")
    if p.is_member and p.user_id != rec["member_id"]:
        forbid()
    return success(serialize.creditpack_view(rec), 200)


def _qs(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v
