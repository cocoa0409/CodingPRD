"""Serializers: entity dict -> public JSON view with computed fields."""

from services import core
from db import DB


def tour_view(t):
    d = dict(t)
    d["royalty_payable_cents"] = core.tour_royalty_payable(t["id"])
    return d


def show_view(s):
    return dict(s)


def product_view(p):
    d = dict(p)
    d["warehouse_stock_by_size"] = core.compute_warehouse_stock(p["id"])
    return d


def show_product_view(sp):
    return dict(sp)


def allocation_view(a):
    d = dict(a)
    d["quantity_sold"] = core.allocation_quantity_sold(a["id"])
    d["quantity_on_hand"] = (
        a["quantity_allocated"]
        - d["quantity_sold"]
        - a["quantity_returned"]
        - a["quantity_liquidated"]
        - a["quantity_shrunk"]
    )
    return d


def seller_view(s):
    return dict(s)


def session_view(s):
    d = dict(s)
    d["expected_cash_cents"] = core.session_expected_cash(s)
    d["cash_variance_cents"] = core.session_variance(s)
    return d


def sale_record_view(r):
    return dict(r)


def online_order_view(o):
    return dict(o)


def settlement_view(s):
    return dict(s)


def shipment_view(s):
    return dict(s)
