"""Inventory resale routes: get, list, sell, recall (PRD §3.8)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth
from models import touch
from helpers import (
    get_body,
    as_int,
    parse_pagination,
    paginate,
    sort_by_creation,
    serialize,
)
from response import success_object, success_array
from services.domain import active_hold_on_inventory_item, rederive_grace

bp = Blueprint("inventory", __name__)


def _drawer_for_shop(shop_id):
    for d in store.cash_drawers.values():
        if d["shop_id"] == shop_id:
            return d
    return None


@bp.route("/pawn/inventory/<inv_id>", methods=["GET"])
def get_inventory(inv_id):
    require_auth(["ShopManager", "LoanOfficer"])
    inv = store.inventory_items.get(inv_id)
    if inv is None:
        raise err("ERR_NOT_FOUND", "Inventory item not found.")
    return success_object(serialize(inv))


@bp.route("/pawn/inventory", methods=["GET"])
def list_inventory():
    require_auth(["ShopManager", "LoanOfficer", "LawEnforcement"])
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    source_loan_id = request.args.get("source_loan_id")
    pawn_item_id = request.args.get("pawn_item_id")
    items = list(store.inventory_items.values())
    if shop_id is not None:
        items = [i for i in items if i["shop_id"] == shop_id]
    if source_loan_id is not None:
        items = [i for i in items if i["source_loan_id"] == source_loan_id]
    if pawn_item_id is not None:
        items = [i for i in items if i["pawn_item_id"] == pawn_item_id]
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(i) for i in window], limit, offset, total)


@bp.route("/pawn/inventory/<inv_id>/sell", methods=["POST"])
def sell_inventory(inv_id):
    require_auth(["ShopManager"])
    inv = store.inventory_items.get(inv_id)
    if inv is None:
        raise err("ERR_NOT_FOUND", "Inventory item not found.")

    body = get_body()
    sold_price_cents = as_int(body, "sold_price_cents")

    # State (priority 5): must be AVAILABLE.
    if inv["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Inventory item is not AVAILABLE.")

    # Police hold (priority 7).
    if active_hold_on_inventory_item(inv_id) is not None:
        raise err("ERR_POLICE_HOLD_ACTIVE", "An active police hold names this item.")

    # Floor price (priority 13).
    if sold_price_cents < inv["floor_price_cents"]:
        raise err("ERR_PRICE_BELOW_FLOOR", "Sale price is below the floor price.")

    inv["sold_price_cents"] = sold_price_cents
    inv["status"] = "SOLD"
    touch(inv)
    drawer = _drawer_for_shop(inv["shop_id"])
    if drawer is not None:
        drawer["balance_cents"] += sold_price_cents
        touch(drawer)
    return success_object(serialize(inv))


@bp.route("/pawn/inventory/<inv_id>/recall", methods=["POST"])
def recall_inventory(inv_id):
    require_auth(["ShopManager"])
    inv = store.inventory_items.get(inv_id)
    if inv is None:
        raise err("ERR_NOT_FOUND", "Inventory item not found.")

    # State (priority 5): must be AVAILABLE, and source loan FORFEITED.
    if inv["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Inventory item is not AVAILABLE.")
    source_loan = store.loans.get(inv["source_loan_id"])
    if source_loan is None or source_loan["status"] != "FORFEITED":
        raise err("ERR_INVALID_STATE", "Source loan is not FORFEITED.")

    # Police hold (priority 7).
    if active_hold_on_inventory_item(inv_id) is not None:
        raise err("ERR_POLICE_HOLD_ACTIVE", "An active police hold names this item.")

    # Item -> RECALLED; source Loan -> IN_GRACE; PawnItem -> PLEDGED (PRD §3.8).
    inv["status"] = "RECALLED"
    touch(inv)
    source_loan["status"] = "IN_GRACE"
    touch(source_loan)
    item = store.pawn_items.get(source_loan["pawn_item_id"])
    if item is not None:
        item["status"] = "PLEDGED"
        touch(item)
    return success_object(serialize(inv))
