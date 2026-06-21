"""Convert internal records to public JSON views.

Most records already carry their public fields directly; the serializers strip
internal (_-prefixed) fields and project shipment computed totals on read."""
from common import round_half_up, public
from inventory import lot_value


def ser_department(d):
    return public(d)


def ser_product(p):
    return public(p)


def ser_lot(l):
    return public(l)


def ser_shipment(s):
    """received_total_cents and variance_cents are computed on read from the
    shipment's lines (sum of accepted_qty * unit_cost, weighed /1000 rounded)."""
    from db import db
    out = public(s)
    received = 0
    for line in db.shipment_lines.values():
        if line["shipment_id"] != s["id"]:
            continue
        product = db.products.get(line["product_id"])
        acc = line["accepted_qty"]
        if product is not None and product["sell_by_weight"]:
            received += round_half_up(acc * line["unit_cost_cents"], 1000)
        else:
            received += acc * line["unit_cost_cents"]
    out["received_total_cents"] = received
    out["variance_cents"] = received - s["expected_total_cents"]
    return out


def ser_shipment_line(line):
    return public(line)


def ser_price_plan(pp):
    return public(pp)


def ser_promotion(pr):
    return public(pr)


def ser_member(m):
    return public(m)


def ser_coupon(c):
    return public(c)


def ser_clip(cc):
    return public(cc)


def ser_sale(s):
    return public(s)


def ser_sale_line(sli):
    return public(sli)


def ser_cycle_count(cc):
    return public(cc)


def ser_eod(e):
    return public(e)
