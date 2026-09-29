"""Tax remittances: basis selection, frozen amounts, period exclusivity (PRD 3.9)."""
from datetime import datetime
from decimal import Decimal

import clock
from rounding import dec, rhu_liters
from store import db, ordered


def _midnight(day):
    return datetime(day.year, day.month, day.day)


def in_half_open(instant, start_date, end_date):
    """[period_start, period_end) -- the key date on period_end belongs to the next period."""
    if instant is None:
        return False
    return _midnight(start_date) <= instant < _midnight(end_date)


def delivered_shipments(order_id):
    return [s for s in db.shipments.values()
            if s["order_id"] == order_id and s["status"] == "DELIVERED"]


def select_orders(winery_id, state_code, basis, start_date, end_date):
    selected = []
    for order in db.orders.values():
        if order["winery_id"] != winery_id:
            continue
        if order["ship_to_state_code"] != state_code:
            continue
        if basis == "ACCRUAL_BASIS":
            if order["compliance_status"] != "CLEARED":
                continue
            if not in_half_open(clock.parse_instant(order.get("cleared_at")),
                                start_date, end_date):
                continue
        else:
            hit = False
            for shipment in delivered_shipments(order["id"]):
                if in_half_open(clock.parse_instant(shipment.get("delivered_at")),
                                start_date, end_date):
                    hit = True
                    break
            if not hit:
                continue
        selected.append(order)
    selected.sort(key=lambda o: (o.get("cleared_at") or "",
                                 o.get("created_at") or "",
                                 o.get("_seq") or 0))
    return selected


def compute_amounts(winery_id, state_code, basis, start_date, end_date):
    selected = select_orders(winery_id, state_code, basis, start_date, end_date)
    excise_accrued = sum(o["excise_tax_cents"] for o in selected)
    sales_accrued = sum(o["sales_tax_cents"] for o in selected)
    reversed_orders = []
    for order in selected:
        returned = clock.parse_instant(order.get("returned_at"))
        if returned is not None and returned < _midnight(end_date):
            reversed_orders.append(order)
    excise_reversed = sum(o["excise_tax_cents"] for o in reversed_orders)
    sales_reversed = sum(o["sales_tax_cents"] for o in reversed_orders)
    liters_total = rhu_liters(sum((dec(o["total_liters"]) for o in selected), Decimal(0)))
    return {
        "excise_accrued_cents": excise_accrued,
        "excise_reversed_cents": excise_reversed,
        "excise_due_cents": excise_accrued - excise_reversed,
        "sales_tax_accrued_cents": sales_accrued,
        "sales_tax_reversed_cents": sales_reversed,
        "sales_tax_due_cents": sales_accrued - sales_reversed,
        "liters_total": liters_total,
        "shipment_count": len(selected),
        "included_order_ids": [o["id"] for o in selected],
    }


def period_collision(winery_id, state_code, period_type, basis, start_date, end_date,
                     exempt_id=None):
    """Half-open exclusivity scoped by (winery, state, period_type, basis)."""
    for row in ordered(list(db.remittances.values())):
        if row["winery_id"] != winery_id or row["state_code"] != state_code:
            continue
        if row["period_type"] != period_type or row["basis"] != basis:
            continue
        if row["status"] == "AMENDED":
            continue
        if exempt_id is not None and row["id"] == exempt_id:
            continue
        other_start = clock.parse_date(row["period_start"])
        other_end = clock.parse_date(row["period_end"])
        if other_start is None or other_end is None:
            continue
        if start_date < other_end and other_start < end_date:
            return row
    return None
