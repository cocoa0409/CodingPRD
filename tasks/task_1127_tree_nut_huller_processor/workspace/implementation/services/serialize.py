"""Entity serializers — inject computed fields and strip internal keys."""
from decimal import Decimal

import db
from services import calc


def _clean(rec, extra=None):
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    if extra:
        out.update(extra)
    return out


def grower_out(g):
    payable = 0
    lifetime = 0
    for s in db.store.settlements.values():
        if s["grower_id"] == g["id"]:
            if s["status"] == "ISSUED":
                payable += s["total_cents"]
            elif s["status"] == "PAID":
                lifetime += s["total_cents"]
    return _clean(g, {
        "payable_outstanding_cents": payable,
        "lifetime_paid_cents": lifetime,
    })


def buyer_out(b):
    return _clean(b)


def lot_out(lot):
    kernel, shell, hull = calc.lot_outputs(lot["id"])
    if lot["intake_moisture_pct"] is None:
        requires_drying = None
    else:
        requires_drying = bool(calc.D(lot["intake_moisture_pct"]) > calc.MOISTURE_STD_PCT)
    return _clean(lot, {
        "kernel_out_lbs": kernel,
        "shell_out_lbs": shell,
        "hull_out_lbs": hull,
        "requires_drying": requires_drying,
    })


def lab_test_out(t):
    return _clean(t)


def run_out(r):
    return _clean(r)


def dryer_out(d):
    return _clean(d)


def batch_out(b):
    return _clean(b)


def bin_out(b):
    occupied, available_now, projected = calc.bin_capacity(b)
    return _clean(b, {
        "occupied_lbs": occupied,
        "available_now_lbs": available_now,
        "projected_available_lbs": projected,
    })


def placement_out(p):
    return _clean(p, {
        "allocated_planned_lbs": calc.placement_allocated_planned_lbs(p["id"]),
    })


def withdrawal_out(w):
    return _clean(w)


def fumigation_out(e):
    return _clean(e)


def contract_out(c):
    reserved, delivered = calc.contract_reserved_delivered(c["id"])
    return _clean(c, {
        "reserved_qty_lbs": reserved,
        "delivered_qty_lbs": delivered,
    })


def shipment_out(s):
    return _clean(s)


def settlement_out(s):
    return _clean(s)


def byproduct_sale_out(s):
    return _clean(s)
