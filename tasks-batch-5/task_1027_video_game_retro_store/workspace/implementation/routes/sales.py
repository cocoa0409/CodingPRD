from flask import Blueprint

import store
import ledger
from calc import sale_totals, loyalty_points
from common import authorize, get_json, need, as_str, as_int
from envelope import object_response
from errors import err

bp = Blueprint("sales", __name__)


@bp.post("/sales")
def create_sale():
    authorize(["Clerk", "Manager"])
    body = get_json()
    # Priority 3: existence of member and each line's inventory item.
    mid = body.get("member_id")
    if mid is not None and mid not in store.members:
        raise err("ERR_NOT_FOUND", "member_id does not exist")
    raw_lines = body.get("lines")
    if isinstance(raw_lines, list):
        for line in raw_lines:
            if isinstance(line, dict):
                iid = line.get("inventory_item_id")
                if iid is not None and iid not in store.inventory_items:
                    raise err("ERR_NOT_FOUND", "inventory_item_id does not exist")
    # Priority 4: schema.
    member_id = as_str(need(body, "member_id"), "member_id")
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        raise err("ERR_VALIDATION", "lines must be a non-empty array")
    lines = []
    for line in raw_lines:
        if not isinstance(line, dict):
            raise err("ERR_VALIDATION", "each line must be an object")
        iid = as_str(need(line, "inventory_item_id"), "inventory_item_id")
        unit_price = as_int(need(line, "unit_price_cents"), "unit_price_cents")
        if unit_price < 0:
            raise err("ERR_VALIDATION", "unit_price_cents must be >= 0")
        qty = as_int(need(line, "qty"), "qty")
        if qty < 1:
            raise err("ERR_VALIDATION", "qty must be >= 1")
        lines.append({"inventory_item_id": iid, "unit_price_cents": unit_price, "qty": qty})
    redeem = 0
    if body.get("redeem_store_credit_cents") is not None:
        redeem = as_int(body["redeem_store_credit_cents"], "redeem_store_credit_cents")
        if redeem < 0:
            raise err("ERR_VALIDATION", "redeem_store_credit_cents must be >= 0")
    member = store.members[member_id]
    # Priority 7: every line's inventory item must be AVAILABLE.
    for line in lines:
        if store.inventory_items[line["inventory_item_id"]]["status"] != "AVAILABLE":
            raise err("ERR_ITEM_NOT_AVAILABLE", "An inventory item in the sale is not AVAILABLE")
    # Priority 16: store-credit sufficiency (after item availability).
    if redeem > member["store_credit_balance_cents"]:
        raise err("ERR_INSUFFICIENT_STORE_CREDIT", "redeem exceeds member store credit balance")
    subtotal, tax_total, total, applied_credit, amount_due = sale_totals(lines, redeem)
    points = loyalty_points(total, applied_credit, member["tier"])
    # Commit: mark items SOLD.
    for line in lines:
        item = store.inventory_items[line["inventory_item_id"]]
        if item["status"] == "AVAILABLE":
            item["status"] = "SOLD"
            store.touch(item)
    sale = store.make_record({
        "member_id": member_id,
        "lines": lines,
        "redeem_store_credit_cents": redeem,
        "subtotal_cents": subtotal,
        "tax_total_cents": tax_total,
        "total_cents": total,
        "amount_due_cents": amount_due,
        "loyalty_points_earned": points,
    })
    store.sales[sale["id"]] = sale
    member["loyalty_points"] = member["loyalty_points"] + points
    if applied_credit > 0:
        ledger.add_entry(member_id, -applied_credit, "SALE_REDEMPTION", sale["id"])
        ledger.recompute_balance(member)
    else:
        store.touch(member)
    return object_response(store.serialize(sale), 201)
