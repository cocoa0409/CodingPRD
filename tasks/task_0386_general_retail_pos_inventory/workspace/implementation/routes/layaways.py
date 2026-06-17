"""Layaway endpoints (PRD §3.9)."""
from flask import Blueprint, request

from db import DB
from middleware import auth_context, require_role
from common import (
    stamp_create, touch, public_view, get_json_body, as_int, as_str,
    parse_pagination, paginate,
)
from response import success, success_list
from errors import (
    err, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_INSUFFICIENT_STOCK, ERR_INVALID_REQUEST,
    ERR_LAYAWAY_NOT_DELINQUENT, ERR_FORBIDDEN_ROLE,
)
from services.inventory import recompute, find_item


bp = Blueprint("layaways", __name__)


def _recompute_balance(layaway):
    layaway["balance_cents"] = layaway["total_price_cents"] - layaway["deposit_paid_cents"]


@bp.route("/layaways", methods=["POST"])
def create_layaway():
    _, role = auth_context()
    require_role(role, {"Cashier", "StoreManager"})
    body = get_json_body()
    store_id = as_str(body, "store_id")
    product_id = as_str(body, "product_id")
    customer_id = as_str(body, "customer_id")
    quantity = as_int(body, "quantity", minimum=1)
    due_date = as_str(body, "due_date")
    initial_deposit = as_int(body, "initial_deposit_cents", required=False,
                             default=0, minimum=0)

    with DB.lock:
        # body FK resolution (priority 4)
        if store_id not in DB.stores:
            raise err(ERR_REFERENCE_NOT_FOUND, "store_id not found")
        if product_id not in DB.products:
            raise err(ERR_REFERENCE_NOT_FOUND, "product_id not found")
        if customer_id not in DB.loyalty_accounts:
            raise err(ERR_REFERENCE_NOT_FOUND, "customer_id not found")
        item = find_item(DB, store_id, product_id)
        if item is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "No inventory item for store/product")
        # stock availability (priority 14): available_qty >= quantity
        if item["available_qty"] < quantity:
            raise err(ERR_INSUFFICIENT_STOCK, "Insufficient available stock for layaway")

        product = DB.products[product_id]
        total_price = product["list_price_cents"] * quantity
        if initial_deposit > total_price:
            raise err(ERR_INVALID_REQUEST, "Initial deposit exceeds total price")
        layaway = {
            "store_id": store_id,
            "product_id": product_id,
            "customer_id": customer_id,
            "quantity": quantity,
            "total_price_cents": total_price,
            "deposit_paid_cents": initial_deposit,
            "balance_cents": total_price - initial_deposit,
            "due_date": due_date,
            "status": "ACTIVE",
        }
        stamp_create(layaway)
        # reserve stock
        item["reserved_qty"] += quantity
        recompute(item)
        DB.layaways[layaway["id"]] = layaway
        # An initial deposit that clears the balance fulfills immediately.
        if layaway["balance_cents"] == 0:
            _fulfill(layaway, item)
        return success(public_view(layaway), status=201)


def _fulfill(layaway, item):
    """FULFILLED side effects (PRD §3.9): reserved_qty and on_hand_qty each
    decremented by quantity; goods leave with the customer."""
    item["reserved_qty"] -= layaway["quantity"]
    item["on_hand_qty"] -= layaway["quantity"]
    recompute(item)
    layaway["status"] = "FULFILLED"


@bp.route("/layaways/<layaway_id>", methods=["GET"])
def get_layaway(layaway_id):
    user_id, role = auth_context()
    require_role(role, {"StoreManager", "Cashier", "Customer"})
    with DB.lock:
        layaway = DB.layaways.get(layaway_id)
        if layaway is None:
            raise err(ERR_NOT_FOUND, "Layaway not found")
        if role == "Customer" and user_id != layaway["customer_id"]:
            raise err(ERR_FORBIDDEN_ROLE, "Customers may only read their own layaways")
        return success(public_view(layaway))


@bp.route("/layaways", methods=["GET"])
def list_layaways():
    user_id, role = auth_context()
    require_role(role, {"StoreManager", "Cashier", "Customer"})
    limit, offset = parse_pagination()
    store_id = request.args.get("store_id")
    product_id = request.args.get("product_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    with DB.lock:
        recs = list(DB.layaways.values())
        if role == "Customer":
            # Customer may list only their own layaways (PRD §2.1)
            recs = [r for r in recs if r["customer_id"] == user_id]
        if store_id is not None:
            recs = [r for r in recs if r["store_id"] == store_id]
        if product_id is not None:
            recs = [r for r in recs if r["product_id"] == product_id]
        if customer_id is not None:
            recs = [r for r in recs if r["customer_id"] == customer_id]
        if status is not None:
            recs = [r for r in recs if r["status"] == status]
        items, total = paginate(recs, limit, offset)
        return success_list(items, limit, offset, total)


@bp.route("/layaways/<layaway_id>/payments", methods=["POST"])
def record_payment(layaway_id):
    _, role = auth_context()
    require_role(role, {"Cashier", "StoreManager"})
    body = get_json_body()
    amount_cents = as_int(body, "amount_cents")
    expected = as_int(body, "expected_layaway_version")
    with DB.lock:
        layaway = DB.layaways.get(layaway_id)
        if layaway is None:
            raise err(ERR_NOT_FOUND, "Layaway not found")
        # OCC (priority 7) before state check (priority 8)
        if expected != layaway["version"]:
            raise err(ERR_STALE_VERSION, "Stale layaway version")
        # Deposits accepted only while ACTIVE or DELINQUENT (PRD §3.9)
        if layaway["status"] not in ("ACTIVE", "DELINQUENT"):
            raise err(ERR_INVALID_STATE, "Layaway is not open for deposits")
        if amount_cents <= 0:
            raise err(ERR_INVALID_REQUEST, "Deposit amount must be positive")
        if amount_cents > layaway["balance_cents"]:
            raise err(ERR_INVALID_REQUEST, "Deposit exceeds outstanding balance")

        layaway["deposit_paid_cents"] += amount_cents
        _recompute_balance(layaway)
        if layaway["balance_cents"] == 0:
            item = find_item(DB, layaway["store_id"], layaway["product_id"])
            _fulfill(layaway, item)
        elif layaway["status"] == "DELINQUENT":
            # deposit leaving balance > 0 while DELINQUENT -> back to ACTIVE
            layaway["status"] = "ACTIVE"
        touch(layaway)
        return success(public_view(layaway))


@bp.route("/layaways/<layaway_id>/forfeit", methods=["POST"])
def forfeit_layaway(layaway_id):
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    with DB.lock:
        layaway = DB.layaways.get(layaway_id)
        if layaway is None:
            raise err(ERR_NOT_FOUND, "Layaway not found")
        # forfeit permitted only while DELINQUENT (PRD §3.9)
        if layaway["status"] != "DELINQUENT":
            raise err(ERR_LAYAWAY_NOT_DELINQUENT, "Layaway is not DELINQUENT")
        item = find_item(DB, layaway["store_id"], layaway["product_id"])
        item["reserved_qty"] -= layaway["quantity"]
        recompute(item)
        layaway["status"] = "FORFEITED"
        touch(layaway)
        return success(public_view(layaway))


@bp.route("/layaways/<layaway_id>/cancel", methods=["POST"])
def cancel_layaway(layaway_id):
    _, role = auth_context()
    require_role(role, {"StoreManager"})
    with DB.lock:
        layaway = DB.layaways.get(layaway_id)
        if layaway is None:
            raise err(ERR_NOT_FOUND, "Layaway not found")
        # cancel permitted only while ACTIVE (PRD §3.9)
        if layaway["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Layaway is not ACTIVE")
        item = find_item(DB, layaway["store_id"], layaway["product_id"])
        item["reserved_qty"] -= layaway["quantity"]
        recompute(item)
        layaway["status"] = "CANCELLED"
        touch(layaway)
        return success(public_view(layaway))
