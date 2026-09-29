"""Stock-position derived figures (PRD 3.1, 3.7)."""
import db


def find_stock(store_id, sku):
    for stock in db.all_of("store_stocks"):
        if stock["store_id"] == store_id and stock["sku"] == sku:
            return stock
    return None


def recompute(store_id, sku):
    """reserved_units is the sum over HELD/ALLOCATED reservations at that store for that SKU."""
    stock = find_stock(store_id, sku)
    if stock is None:
        return None
    reserved = 0
    for res in db.all_of("reservations"):
        if res["store_id"] == store_id and res["sku"] == sku and res["status"] in ("HELD", "ALLOCATED"):
            reserved += res["qty_units"]
    stock["reserved_units"] = reserved
    stock["available_units"] = stock["on_hand_units"] - reserved
    db.touch(stock)
    return stock


def available_units(store_id, sku):
    stock = find_stock(store_id, sku)
    if stock is None:
        return 0
    return stock["on_hand_units"] - stock["reserved_units"]
