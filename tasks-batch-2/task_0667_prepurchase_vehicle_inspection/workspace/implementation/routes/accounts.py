"""Account endpoints (PRD §3.1)."""
from flask import Blueprint, g

from db import db, stamp_create, touch
from errors import err
from helpers import (check_enum, get_json_body, paginate, parse_pagination,
                     require_fields, serialize, sort_by_created)
from middleware import require_roles
from response import success
from services.lookups import get_account

bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = {"DEALER", "AUCTION", "INDIVIDUAL"}


def compute_outstanding_balance(account_id):
    """Sum fee_total_cents over this account's orders in INVOICED payment status."""
    total = 0
    for o in db.orders.values():
        if o["account_id"] == account_id and o["payment_status"] == "INVOICED":
            total += int(o.get("fee_total_cents", 0))
    return total


def serialize_account(acct):
    out = serialize(acct)
    out["outstanding_balance_cents"] = acct.get("outstanding_balance_cents", 0)
    return out


@bp.route("/accounts", methods=["POST"])
@require_roles("OpsAdmin")
def create_account():
    body = get_json_body()
    require_fields(body, ["account_type", "legal_name", "email"])
    check_enum(body["account_type"], ACCOUNT_TYPES, "account_type")

    net_terms = body.get("net_terms_days", 0)
    if net_terms is None:
        net_terms = 0
    if not isinstance(net_terms, int) or isinstance(net_terms, bool) or net_terms < 0:
        raise err("ERR_INVALID_REQUEST", "net_terms_days must be a non-negative integer")

    rush_disc = body.get("rush_discount_pct", 0)
    if rush_disc is None:
        rush_disc = 0
    if not isinstance(rush_disc, (int, float)) or isinstance(rush_disc, bool):
        raise err("ERR_INVALID_REQUEST", "rush_discount_pct must be numeric")
    if rush_disc < 0 or rush_disc > 0.50:
        raise err("ERR_INVALID_REQUEST", "rush_discount_pct must be within [0, 0.50]")

    acct = {
        "account_type": body["account_type"],
        "legal_name": body["legal_name"],
        "email": body["email"],
        "net_terms_days": net_terms,
        "rush_discount_pct": rush_disc,
        "status": "ACTIVE",
        "outstanding_balance_cents": 0,
    }
    stamp_create(acct)
    db.accounts[acct["id"]] = acct
    return success(serialize_account(acct), status=201)


@bp.route("/accounts/<account_id>", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def get_account_ep(account_id):
    acct = get_account(account_id)
    return success(serialize_account(acct), status=200)


@bp.route("/accounts/<account_id>/suspend", methods=["POST"])
@require_roles("OpsAdmin")
def suspend_account(account_id):
    acct = get_account(account_id)
    acct["status"] = "SUSPENDED"
    touch(acct)
    return success(serialize_account(acct), status=200)


@bp.route("/accounts/<account_id>/orders", methods=["GET"])
@require_roles("OpsAdmin", "AccountHolder")
def list_account_orders(account_id):
    from routes.orders import serialize_order
    get_account(account_id)
    limit, offset = parse_pagination()
    items = [o for o in db.orders.values() if o["account_id"] == account_id]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([serialize_order(o) for o in page], status=200, pagination=meta)
