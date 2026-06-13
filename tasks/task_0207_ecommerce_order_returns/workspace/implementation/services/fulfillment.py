"""Re-derivation of Order.fulfillment_status from child shipments (PRD §3.5)."""
from db import db
from services import derive


def _order_lines_of(order_id):
    return [l for l in db.order_lines.values() if l["order_id"] == order_id]


def rederive_fulfillment(order):
    """Recompute Order.fulfillment_status from underlying shipments.

    SHIPPED once every non-backordered unit has shipped, else PARTIALLY_SHIPPED;
    DELIVERED once every shipped unit has been delivered, else
    PARTIALLY_DELIVERED. BACKORDERED is preserved only while nothing has shipped
    and a backorder exists. Does NOT touch the order; callers decide that.
    """
    lines = _order_lines_of(order["id"])

    total_non_backordered = sum(L["qty"] - L.get("backordered_qty", 0) for L in lines)
    total_shipped = 0
    total_delivered = 0
    for L in lines:
        shipped = derive.order_line_shipped_qty(L["id"])
        total_shipped += shipped
        # delivered units for this line
        delivered = 0
        for sl in db.shipment_lines.values():
            if sl["order_line_id"] != L["id"]:
                continue
            ship = db.shipments.get(sl["shipment_id"])
            if ship and ship["status"] == "DELIVERED":
                delivered += sl["qty"]
        total_delivered += delivered

    any_backorder = any(L.get("backordered_qty", 0) > 0 for L in lines)

    if total_shipped == 0:
        # nothing shipped yet -> keep backorder/unfulfilled
        order["fulfillment_status"] = "BACKORDERED" if any_backorder else "UNFULFILLED"
        return

    if total_delivered > 0:
        if total_delivered >= total_shipped:
            order["fulfillment_status"] = "DELIVERED"
        else:
            order["fulfillment_status"] = "PARTIALLY_DELIVERED"
        return

    # something shipped, nothing delivered
    if total_shipped >= total_non_backordered and total_non_backordered > 0:
        order["fulfillment_status"] = "SHIPPED"
    else:
        order["fulfillment_status"] = "PARTIALLY_SHIPPED"
