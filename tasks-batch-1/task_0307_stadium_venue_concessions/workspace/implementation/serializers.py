"""Public serializers for each entity.

Internal records carry private bookkeeping keys (prefixed with "_") and store
some values as datetime objects; serializers project the public field set in the
shapes the PRD describes. Field names trace to SCAFFOLD §1.1 / PRD §3.
"""

from db import _iso_millis


def _dt(value):
    """Serialize a stored datetime (or None) as ISO 8601 UTC millis."""
    if value is None:
        return None
    return _iso_millis(value)


def _common(obj, with_version=True):
    out = {
        "id": obj["id"],
        "created_at": obj["created_at"],
    }
    if with_version:
        out["updated_at"] = obj["updated_at"]
        out["version"] = obj["version"]
    return out


def venue(o):
    d = _common(o)
    d.update({
        "name": o["name"],
        "venue_share_pct": o["venue_share_pct"],
        "service_fee_pct": o["service_fee_pct"],
        "share_basis": o["share_basis"],
        "spoilage_valuation": o["spoilage_valuation"],
    })
    return d


def product(o):
    d = _common(o)
    d.update({
        "venue_id": o["venue_id"],
        "sku": o["sku"],
        "name": o["name"],
        "base_price_cents": o["base_price_cents"],
        "unit_cost_cents": o["unit_cost_cents"],
        "perishable": o["perishable"],
    })
    return d


def event(o):
    d = _common(o)
    d.update({
        "venue_id": o["venue_id"],
        "name": o["name"],
        "doors_time": _dt(o["doors_time"]),
        "end_time": _dt(o["end_time"]),
        "event_multiplier_pct": o["event_multiplier_pct"],
        "peak_window": o["peak_window"],
        "status": o["status"],
        "gross_sales_cents": o["gross_sales_cents"],
        "waste_cost_cents": o["waste_cost_cents"],
    })
    return d


def stand(o):
    d = _common(o)
    d.update({
        "event_id": o["event_id"],
        "name": o["name"],
        "demand_tier": o["demand_tier"],
        "expected_orders_per_hour": o["expected_orders_per_hour"],
        "status": o["status"],
        "required_staff": o["required_staff"],
        "assigned_staff_count": o["assigned_staff_count"],
    })
    return d


def menu_item(o):
    d = _common(o)
    d.update({
        "stand_id": o["stand_id"],
        "product_id": o["product_id"],
        "available": o["available"],
        "price_cents": o["price_cents"],
    })
    return d


def inventory_lot(o):
    d = _common(o)
    d.update({
        "stand_id": o["stand_id"],
        "product_id": o["product_id"],
        "received_qty": o["received_qty"],
        "remaining_qty": o["remaining_qty"],
        "unit_cost_cents": o["unit_cost_cents"],
        "par_level": o["par_level"],
        "reorder_point": o["reorder_point"],
        "expires_at": _dt(o["expires_at"]),
        "status": o["status"],
    })
    return d


def replenishment(o):
    d = _common(o)
    d.update({
        "stand_id": o["stand_id"],
        "product_id": o["product_id"],
        "requested_qty": o["requested_qty"],
        "fulfilled_qty": o["fulfilled_qty"],
        "status": o["status"],
    })
    return d


def transfer(o):
    d = _common(o)
    d.update({
        "from_stand_id": o["from_stand_id"],
        "to_stand_id": o["to_stand_id"],
        "product_id": o["product_id"],
        "qty": o["qty"],
        "status": o["status"],
    })
    return d


def order(o):
    d = _common(o)
    d.update({
        "event_id": o["event_id"],
        "stand_id": o["stand_id"],
        "patron_id": o["patron_id"],
        "subtotal_cents": o["subtotal_cents"],
        "service_fee_cents": o["service_fee_cents"],
        "total_cents": o["total_cents"],
        "payment_status": o["payment_status"],
        "fulfillment_status": o["fulfillment_status"],
    })
    return d


def order_line(o):
    d = _common(o)
    d.update({
        "order_id": o["order_id"],
        "menu_item_id": o["menu_item_id"],
        "qty": o["qty"],
        "unit_price_cents": o["unit_price_cents"],
        "line_subtotal_cents": o["line_subtotal_cents"],
        "line_fee_cents": o["line_fee_cents"],
    })
    return d


def staff_shift(o):
    d = _common(o)
    d.update({
        "stand_id": o["stand_id"],
        "worker_name": o["worker_name"],
        "shift_start": _dt(o["shift_start"]),
        "shift_end": _dt(o["shift_end"]),
        "status": o["status"],
    })
    return d


def waste_record(o):
    # WasteRecord is leaner: only id + created_at (PRD §2.4).
    d = _common(o, with_version=False)
    d.update({
        "stand_id": o["stand_id"],
        "product_id": o["product_id"],
        "lot_id": o["lot_id"],
        "reason": o["reason"],
        "qty": o["qty"],
        "cost_cents": o["cost_cents"],
    })
    return d


def revenue_share_statement(o):
    d = _common(o)
    d.update({
        "event_id": o["event_id"],
        "gross_sales_cents": o["gross_sales_cents"],
        "waste_cost_cents": o["waste_cost_cents"],
        "venue_share_cents": o["venue_share_cents"],
        "operator_net_cents": o["operator_net_cents"],
    })
    return d


def patron(o):
    d = _common(o)
    d.update({
        "display_name": o["display_name"],
        "wallet_credit_cents": o["wallet_credit_cents"],
    })
    return d
