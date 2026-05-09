from decimal import Decimal
from flask import Blueprint, request
from auth import require_role
from db import db, make_common_fields, bump
from envelope import success, created
from errors import APIError, ERR_NOT_FOUND, ERR_FORBIDDEN
from validation import need_body, require_str, require_decimal, occ_check
from serializers import serialize_user
from common import to_money

bp = Blueprint("users", __name__)

DEPOSIT_CAP = Decimal("99.00")


@bp.post("/users")
def create_user():
    require_role({"Admin"})
    body = need_body(request.get_json(silent=True))
    phone = require_str(body, "phone")

    cf = make_common_fields()
    user = {
        **cf,
        "phone": phone,
        "wallet_balance": Decimal("0.00"),
        "deposit_balance": Decimal("0.00"),
        "refund_count_30d": 0,
        "borrow_count_24h": 0,
    }
    db.users[user["id"]] = user
    return created(serialize_user(user))


@bp.get("/users/<user_id>")
def get_user(user_id):
    uid, role = require_role({"Admin", "User"})
    user = db.users.get(user_id)
    if user is None:
        raise APIError(ERR_NOT_FOUND, 404, "User not found")
    if role == "User" and user["id"] != uid:
        raise APIError(ERR_FORBIDDEN, 403, "Cannot read another user's record")
    return success(serialize_user(user))


@bp.post("/users/<user_id>/wallet/topup")
def wallet_topup(user_id):
    uid, role = require_role({"User"})
    user = db.users.get(user_id)
    if user is None:
        raise APIError(ERR_NOT_FOUND, 404, "User not found")
    if user["id"] != uid:
        raise APIError(ERR_FORBIDDEN, 403, "Cannot top up another user's wallet")
    body = need_body(request.get_json(silent=True))
    amount = to_money(require_decimal(body, "amount", strictly_positive=True))
    occ_check(user, body)
    user["wallet_balance"] = to_money(user["wallet_balance"] + amount)
    bump(user)
    return success(serialize_user(user))


@bp.post("/users/<user_id>/deposit")
def deposit(user_id):
    uid, role = require_role({"User"})
    user = db.users.get(user_id)
    if user is None:
        raise APIError(ERR_NOT_FOUND, 404, "User not found")
    if user["id"] != uid:
        raise APIError(ERR_FORBIDDEN, 403, "Cannot deposit to another user")
    body = need_body(request.get_json(silent=True))
    amount = to_money(require_decimal(body, "amount", strictly_positive=True))
    occ_check(user, body)

    new_total = user["deposit_balance"] + amount
    if new_total > DEPOSIT_CAP:
        accepted = DEPOSIT_CAP - user["deposit_balance"]
        if accepted < 0:
            accepted = Decimal("0.00")
        user["deposit_balance"] = to_money(user["deposit_balance"] + accepted)
    else:
        user["deposit_balance"] = to_money(new_total)
    bump(user)
    return success(serialize_user(user))
