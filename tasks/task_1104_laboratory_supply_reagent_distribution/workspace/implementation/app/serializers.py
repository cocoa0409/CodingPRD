"""Resource serializers — exact field sets per entity table."""
from .db import db, fmt_logical


def _strip(rec):
    return {k: v for k, v in rec.items() if not k.startswith('_')}


def warehouse(w):
    return _strip(w)


def zone(z):
    out = _strip(z)
    out['occupied_units'] = zone_occupied(z['id'])
    return out


def product(p):
    return _strip(p)


def lot(l):
    out = _strip(l)
    out.pop('_received_dt', None)
    out['received_at'] = fmt_logical(l['_received_dt'])
    return out


def customer(c):
    out = _strip(c)
    out['outstanding_balance_cents'] = outstanding_balance(c['id'])
    return out


def order(o):
    out = _strip(o)
    out['lines'] = [order_line(l) for l in lines_of_order(o['id'])]
    return out


def order_line(l):
    out = _strip(l)
    out['allocated_quantity'] = allocated_quantity(l['id'])
    return out


def reservation(r):
    return _strip(r)


def shipment(s):
    return _strip(s)


def excursion(e):
    return _strip(e)


def standing_order(so):
    return _strip(so)


def agreement(a):
    return _strip(a)


def consumption_record(r):
    out = _strip(r)
    out.pop('_seq', None)
    out['recorded_at'] = fmt_logical(r['_recorded_dt'])
    return out


def recall(r):
    return _strip(r)


def kit(k):
    return _strip(k)


def job(j):
    return _strip(j)


# ---- derived helpers ----

def zone_occupied(zone_id):
    total = 0
    for l in db.lots.values():
        if l['storage_zone_id'] == zone_id and l['status'] in ('AVAILABLE', 'QUARANTINED'):
            total += l['quantity_on_hand']
    return total


def allocated_quantity(line_id):
    total = 0
    for r in db.reservations.values():
        if r['order_line_id'] == line_id and r['status'] in ('HELD', 'COMMITTED'):
            total += r['quantity']
    return total


def lines_of_order(order_id):
    return sorted([l for l in db.order_lines.values() if l['order_id'] == order_id],
                  key=lambda l: l['_seq'])


def outstanding_balance(customer_id):
    """customer_outstanding_and_credit: shipped invoices + charges - payments,
    floored at zero. REFUNDED orders contribute nothing."""
    raw = 0
    for o in db.orders.values():
        if o['customer_id'] != customer_id:
            continue
        if o['status'] in ('SHIPPED', 'DELIVERED'):
            ship = shipment_of_order(o['id'])
            freight = ship['final_freight_cents'] if ship else 0
            raw += (o['product_total_cents'] or 0) + (freight or 0)
    agreement_ids = [a['id'] for a in db.agreements.values()
                     if a['customer_id'] == customer_id]
    for r in db.consumption_records.values():
        if r['agreement_id'] in agreement_ids:
            raw += r['charge_cents']
    for p in db.payments:
        if p['customer_id'] == customer_id:
            raw -= p['amount_cents']
    return max(0, raw)


def shipment_of_order(order_id):
    for s in db.shipments.values():
        if s['order_id'] == order_id:
            return s
    return None
