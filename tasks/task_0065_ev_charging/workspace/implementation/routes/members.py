"""Member endpoints."""

from flask import Blueprint, g, request

import db
from errors import raise_error
from middleware import require_roles
from response import success
from validators import (
    check_version,
    parse_json_body,
    require_int,
    require_str,
)


bp = Blueprint("members", __name__)

VALID_TIERS = {"BASIC", "SILVER", "GOLD", "PLATINUM"}


@bp.post("/members")
@require_roles({"PlatformOperator", "CustomerService"})
def create_member():
    body = parse_json_body()
    display_name = require_str(body, "display_name", 1, 80)
    home_operator_id = require_str(body, "home_operator_id")
    tier = body.get("tier", "BASIC")
    if tier not in VALID_TIERS:
        raise_error("ERR_VALIDATION", "tier invalid")
    if home_operator_id not in db.operators:
        raise_error("ERR_NOT_FOUND", "home_operator_id not found")

    record = {
        "display_name": display_name,
        "home_operator_id": home_operator_id,
        "tier": tier,
        "no_show_strikes": 0,
        "wallet_balance_cents": 0,
    }
    db.with_common_fields(record)
    db.members[record["id"]] = record
    return success(db.public(record), status=201)


@bp.get("/members/<member_id>")
@require_roles({"PlatformOperator", "CustomerService", "EVDriver"})
def get_member(member_id: str):
    member = db.members.get(member_id)
    if member is None:
        raise_error("ERR_NOT_FOUND", "member not found")
    if g.role == "EVDriver" and g.user_id != member_id:
        raise_error("ERR_FORBIDDEN", "EVDriver can only read own record")
    return success(db.public(member))


@bp.post("/members/<member_id>/wallet-credit")
@require_roles({"PlatformOperator", "CustomerService"})
def credit_wallet(member_id: str):
    member = db.members.get(member_id)
    if member is None:
        raise_error("ERR_NOT_FOUND", "member not found")
    body = parse_json_body()
    check_version(body, member)
    amount_cents = require_int(body, "amount_cents", 1)
    member["wallet_balance_cents"] = int(member["wallet_balance_cents"]) + amount_cents
    db.bump(member)
    return success(db.public(member))
