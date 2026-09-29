"""Consumption of reservations and order fulfilment (PRD 3.8)."""
import clock
import db
from services import stock as stock_svc


def consume_and_fulfil(order):
    """The single mechanism shared by will-call pickup and delivery completion."""
    for res in db.where("reservations", pro_order_id=order["id"]):
        if res["status"] not in ("HELD", "ALLOCATED"):
            continue
        res["status"] = "CONSUMED"
        db.touch(res)
        stock = stock_svc.find_stock(res["store_id"], res["sku"])
        if stock is not None:
            stock["on_hand_units"] = stock["on_hand_units"] - res["qty_units"]
            db.touch(stock)
            stock_svc.recompute(res["store_id"], res["sku"])

    for line in db.where("order_lines", pro_order_id=order["id"]):
        line["fulfilled_units"] = line["qty_units"]
        db.touch(line)

    order["fulfilled_at"] = clock.now_iso()
    order["_fulfilled_at"] = clock.get_now()
    order["fulfillment_status"] = "FULFILLED"
    db.touch(order)
    return order
