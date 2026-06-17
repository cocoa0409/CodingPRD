"""LoyaltyAccount endpoints (PRD §3.8)."""
from flask import Blueprint

from db import DB
from middleware import auth_context, require_role
from common import stamp_create, touch, public_view, get_json_body, as_int, as_str
from response import success
from errors import (
    err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_DUPLICATE_RESOURCE,
    ERR_FORBIDDEN_ROLE,
)
from services.loyalty import recompute_tier

bp = Blueprint("loyalty", __name__)


@bp.route("/loyalty-accounts", methods=["POST"])
def create_account():
    _, role = auth_context()
    require_role(role, {"StoreManager", "Cashier"})
    body = get_json_body()
    customer_name = as_str(body, "customer_name")
    phone = as_str(body, "phone")
    with DB.lock:
        for a in DB.loyalty_accounts.values():
            if a["phone"] == phone:
                raise err(ERR_DUPLICATE_RESOURCE, "Phone already enrolled")
        acct = {
            "customer_name": customer_name,
            "phone": phone,
            "points_balance": 0,
            "lifetime_points": 0,
            "tier": "STANDARD",
        }
        stamp_create(acct)
        DB.loyalty_accounts[acct["id"]] = acct
        return success(public_view(acct), status=201)


@bp.route("/loyalty-accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    user_id, role = auth_context()
    require_role(role, {"StoreManager", "Cashier", "Customer"})
    with DB.lock:
        acct = DB.loyalty_accounts.get(account_id)
        if acct is None:
            raise err(ERR_NOT_FOUND, "Loyalty account not found")
        # Customer may read only their own account (PRD §2.1)
        if role == "Customer" and user_id != acct["id"]:
            raise err(ERR_FORBIDDEN_ROLE, "Customers may only read their own account")
        return success(public_view(acct))


@bp.route("/_loyalty/grant", methods=["POST"])
def grant_points():
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    body = get_json_body()
    account_id = as_str(body, "loyalty_account_id")
    add_points = as_int(body, "add_points")
    with DB.lock:
        acct = DB.loyalty_accounts.get(account_id)
        if acct is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "loyalty_account_id not found")
        acct["points_balance"] += add_points
        acct["lifetime_points"] += add_points
        recompute_tier(acct)
        touch(acct)
        return success(public_view(acct))
