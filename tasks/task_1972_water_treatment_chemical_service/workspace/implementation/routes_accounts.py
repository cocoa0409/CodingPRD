"""CustomerAccount endpoints: create/list/get + suspend/reactivate/close."""

from flask import Blueprint, g

import errors
from calc import recompute_posture
from db import db, create_entity, touch
from helpers import list_response, account_of_account, query_filter
from response import success_object
from serializers import account as ser
from validate import get_body, validate_shape, resolve, check_cc_ownership

bp = Blueprint("accounts", __name__)


@bp.route("/wt/accounts", methods=["POST"])
def create_account():
    body = get_body()
    vals = validate_shape(body, [
        ("account_name", "str", True),
        ("credit_hold", "bool", False),
        ("billing_model", "str", False, ("PRODUCT", "SERVICE_CONTRACT")),
    ])
    ent = create_entity("accounts", {
        "account_name": vals["account_name"],
        "credit_hold": vals["credit_hold"] if vals["credit_hold"] is not None else False,
        "billing_model": vals["billing_model"] or "PRODUCT",
        "open_balance_cents": 0,
        "status": "ACTIVE",
    })
    return success_object(ser(ent), 201)


@bp.route("/wt/accounts", methods=["GET"])
def list_accounts():
    user = (g.role, g.user_id)
    items = list(db["accounts"].values())
    status = query_filter("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, ser, account_of_account, user)


@bp.route("/wt/accounts/<accountId>", methods=["GET"])
def get_account(accountId):
    ent = db["accounts"].get(accountId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, ent["id"])
    ent = resolve("accounts", accountId)
    return success_object(ser(ent), 200)


@bp.route("/wt/accounts/<accountId>/suspend", methods=["POST"])
def suspend_account(accountId):
    ent = resolve("accounts", accountId)
    if ent["status"] != "ACTIVE":
        raise errors.invalid_state("Account must be ACTIVE to suspend")
    ent["status"] = "SUSPENDED"
    touch(ent)
    # Cascade: open delivery orders -> CANCELLED; every asset posture -> FROZEN.
    for order in db["delivery_orders"].values():
        if order["account_id"] == ent["id"] and order["status"] in ("DRAFT", "PENDING", "SCHEDULED"):
            order["status"] = "CANCELLED"
            touch(order)
    for asset in db["assets"].values():
        if asset["account_id"] == ent["id"]:
            recompute_posture(asset)
    return success_object(ser(ent), 200)


@bp.route("/wt/accounts/<accountId>/reactivate", methods=["POST"])
def reactivate_account(accountId):
    ent = resolve("accounts", accountId)
    if ent["status"] != "SUSPENDED":
        raise errors.invalid_state("Account must be SUSPENDED to reactivate")
    ent["status"] = "ACTIVE"
    touch(ent)
    for asset in db["assets"].values():
        if asset["account_id"] == ent["id"]:
            recompute_posture(asset)
    return success_object(ser(ent), 200)


@bp.route("/wt/accounts/<accountId>/close", methods=["POST"])
def close_account(accountId):
    ent = resolve("accounts", accountId)
    if ent["status"] != "ACTIVE":
        raise errors.invalid_state("Account must be ACTIVE to close")
    if ent["open_balance_cents"] != 0:
        raise errors.ApiError(errors.ERR_UNPAID_BALANCE, 409,
                              "Account cannot be closed while open_balance_cents is non-zero")
    ent["status"] = "CLOSED"
    touch(ent)
    for asset in db["assets"].values():
        if asset["account_id"] == ent["id"] and asset["status"] != "DECOMMISSIONED":
            asset["status"] = "DECOMMISSIONED"
            touch(asset)
    return success_object(ser(ent), 200)
