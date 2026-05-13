"""Member and wallet endpoints."""
from flask import Blueprint, request, g
from db import state, new_id, stamp_create, bump
from errors import raise_err
from response import success_object, success_array
from middleware import require_roles, is_role
from routes.helpers import (
    get_json, parse_pagination, paginate, sort_by_created,
    require_member_ownership, check_occ,
)
from serializers import serialize_member, serialize_wallet_transaction
from services import wallet as wallet_svc


bp = Blueprint("members", __name__)


def _validate_email(s):
    if not isinstance(s, str) or "@" not in s or "." not in s:
        raise_err("ERR_VALIDATION", "invalid email")


def _validate_phone(s):
    if not isinstance(s, str) or not s:
        raise_err("ERR_VALIDATION", "invalid phone")
    # E.164 digits only — allow optional leading +
    digits = s
    if digits.startswith("+"):
        digits = digits[1:]
    if not digits.isdigit():
        raise_err("ERR_VALIDATION", "phone must be E.164 digits only")


def _validate_channels(channels):
    valid = {"SMS", "EMAIL", "IM", "PUSH"}
    if not isinstance(channels, list):
        raise_err("ERR_VALIDATION", "notification_channels must be array")
    for c in channels:
        if c not in valid:
            raise_err("ERR_VALIDATION", f"invalid channel: {c}")


@bp.route("/members", methods=["POST"])
def create_member():
    require_roles("PlatformAdmin", "StaffOps")
    body = get_json()
    full_name = body.get("full_name")
    if not isinstance(full_name, str) or not (1 <= len(full_name) <= 120):
        raise_err("ERR_VALIDATION", "full_name length 1..120")
    phone = body.get("phone")
    _validate_phone(phone)
    email = body.get("email")
    _validate_email(email)
    # Uniqueness
    for m in state["members"].values():
        if m["phone"] == phone:
            raise_err("ERR_VALIDATION", "phone already used")
        if m["email"] == email:
            raise_err("ERR_VALIDATION", "email already used")
    family_group_id = body.get("family_group_id")
    channels = body.get("notification_channels", ["SMS", "EMAIL"])
    _validate_channels(channels)
    auto_renew = bool(body.get("auto_renew_authorized", False))
    m = {
        "id": new_id(),
        "full_name": full_name,
        "phone": phone,
        "email": email,
        "family_group_id": family_group_id,
        "notification_channels": channels,
        "auto_renew_authorized": auto_renew,
    }
    stamp_create(m)
    state["members"][m["id"]] = m
    return success_object(serialize_member(m), status=201)


@bp.route("/members/<id_>", methods=["GET"])
def get_member(id_):
    require_roles("PlatformAdmin", "StaffOps", "Member")
    m = state["members"].get(id_)
    if not m:
        raise_err("ERR_NOT_FOUND", "member not found")
    require_member_ownership(id_)
    return success_object(serialize_member(m))


@bp.route("/members/<id_>", methods=["PATCH"])
def patch_member(id_):
    require_roles("PlatformAdmin", "StaffOps", "Member")
    m = state["members"].get(id_)
    if not m:
        raise_err("ERR_NOT_FOUND", "member not found")
    require_member_ownership(id_)
    body = get_json()
    check_occ(m, body)
    if "notification_channels" in body and body["notification_channels"] is not None:
        _validate_channels(body["notification_channels"])
        m["notification_channels"] = list(body["notification_channels"])
    if "auto_renew_authorized" in body and body["auto_renew_authorized"] is not None:
        if not isinstance(body["auto_renew_authorized"], bool):
            raise_err("ERR_VALIDATION", "auto_renew_authorized must be boolean")
        m["auto_renew_authorized"] = body["auto_renew_authorized"]
    if "family_group_id" in body:
        m["family_group_id"] = body["family_group_id"]
    bump(m)
    return success_object(serialize_member(m))


@bp.route("/members/<id_>/wallet/recharge", methods=["POST"])
def wallet_recharge(id_):
    require_roles("Member", "StaffOps", "PlatformAdmin")
    m = state["members"].get(id_)
    if not m:
        raise_err("ERR_NOT_FOUND", "member not found")
    require_member_ownership(id_)
    body = get_json()
    amount = body.get("amount_cents")
    if not isinstance(amount, int):
        raise_err("ERR_VALIDATION", "amount_cents must be integer")
    if amount <= 0 or amount > 1_000_000:
        raise_err("ERR_RECHARGE_AMOUNT_INVALID", "amount_cents out of range")
    rows = wallet_svc.recharge(id_, amount)
    return success_object(
        [serialize_wallet_transaction(r) for r in rows],
        status=201,
    )


@bp.route("/members/<id_>/wallet/quote", methods=["GET"])
def wallet_quote(id_):
    require_roles("Member", "StaffOps")
    m = state["members"].get(id_)
    if not m:
        raise_err("ERR_NOT_FOUND", "member not found")
    require_member_ownership(id_)
    try:
        amount = int(request.args.get("amount_cents", "0"))
    except ValueError:
        raise_err("ERR_VALIDATION", "amount_cents must be integer")
    if amount <= 0:
        raise_err("ERR_VALIDATION", "amount_cents > 0")
    service_type = request.args.get("service_type")
    q = wallet_svc.quote_debit(id_, amount, service_type=service_type)
    # Convert datetime values to ISO strings
    from clock import to_iso_ms
    for d in q.get("bonus_draws", []):
        if d.get("expires_at") is not None:
            d["expires_at"] = to_iso_ms(d["expires_at"])
    return success_object(q)


@bp.route("/members/<id_>/wallet/transactions", methods=["GET"])
def wallet_transactions(id_):
    require_roles("Member", "StaffOps", "PlatformAdmin")
    m = state["members"].get(id_)
    if not m:
        raise_err("ERR_NOT_FOUND", "member not found")
    require_member_ownership(id_)
    limit, offset = parse_pagination()
    kind = request.args.get("kind")
    bucket = request.args.get("bucket")
    items = [t for t in state["wallet_transactions"].values() if t["member_id"] == id_]
    if kind:
        items = [t for t in items if t["kind"] == kind]
    if bucket:
        items = [t for t in items if t["bucket"] == bucket]
    items = sort_by_created(items)
    sliced, meta = paginate(items, limit, offset)
    return success_array([serialize_wallet_transaction(x) for x in sliced], meta)
