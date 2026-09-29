"""Card accounts: enrolment, reads and closure (PRD 3.1)."""

from flask import Blueprint, request

from auth import caller_id, endpoint, require_ownership
from core import clock_iso, fmt_dt, must_find, new_row, ok, store, touch
from errors import ApiError
from rhelp import require_state
from shapes import body, opt_string, req_dt, req_enum, req_string
from svc_ledger import account_entitlements, in_flight_orders, in_flight_transfers, refresh_account
from svc_pricing import CARD_PRODUCTS
from views import ADMIN, OPS, OPS_CARD, account_view, listing

bp = Blueprint("accounts", __name__)


def new_account(data):
    return {
        "cardholder_name": data["cardholder_name"],
        "email": data["email"],
        "card_product_code": data["card_product_code"],
        "enrolled_at": data["enrolled_at"],
        "status": "ACTIVE",
        "fraud_posture": "CLEAR",
        "points_balance": 0,
        "points_pending_redemption": 0,
        "lifetime_points_earned": 0,
        "lifetime_points_redeemed": 0,
        "transfer_hold_count": 0,
        "terms_notice_id": None,
        "pending_notice_id": None,
        "grandfather_expires_at": None,
        "closed_at": None,
    }


@bp.post("/accounts")
@endpoint(ADMIN)
def create_account():
    data = body()
    payload = {
        "cardholder_name": req_string(data, "cardholder_name"),
        "email": req_string(data, "email"),
        "card_product_code": req_enum(data, "card_product_code", CARD_PRODUCTS),
        "enrolled_at": fmt_dt(req_dt(data, "enrolled_at")),
    }
    row = store("accounts", new_row("accounts", new_account(payload)))
    return ok(account_view(row), 201)


@bp.get("/accounts/<account_id>")
@endpoint(OPS_CARD)
def read_account(account_id):
    require_ownership(account_id)
    account = must_find("accounts", account_id)
    return ok(account_view(account))


@bp.get("/accounts")
@endpoint(OPS)
def list_accounts():
    args = request.args
    filters = {
        "status": args.get("status"),
        "fraud_posture": args.get("fraud_posture"),
        "card_product_code": args.get("card_product_code"),
        "terms_notice_id": args.get("terms_notice_id"),
        "pending_notice_id": args.get("pending_notice_id"),
    }
    return listing("accounts", args, filters, account_view)


@bp.post("/accounts/<account_id>/close")
@endpoint(ADMIN)
def close_account(account_id):
    account = must_find("accounts", account_id)
    require_state(account, ("ACTIVE",))
    if in_flight_transfers(account_id) or in_flight_orders(account_id):
        raise ApiError(
            "ERR_ACCOUNT_HAS_IN_FLIGHT_POINTS",
            "Account '%s' still has points in flight." % account_id,
        )
    account["status"] = "CLOSED"
    account["closed_at"] = clock_iso()
    touch(account)
    for entitlement in account_entitlements(account_id, ("ACTIVE",)):
        entitlement["status"] = "EXPIRED"
        touch(entitlement)
    return ok(account_view(account))
