"""Existence lookups. A missing resource raises ERR_NOT_FOUND (PRD §2.5).

References are validated left-to-right by the calling route; each helper here
resolves a single id from a collection.
"""
import db
import errors


def _get(coll, _id):
    if _id is None:
        raise errors.not_found()
    rec = coll.get(_id)
    if rec is None:
        raise errors.not_found()
    return rec


def distributor(_id):
    return _get(db.distributors, _id)


def warehouse(_id):
    return _get(db.warehouses, _id)


def route(_id):
    return _get(db.routes, _id)


def product(_id):
    return _get(db.products, _id)


def price_tier(_id):
    return _get(db.price_tiers, _id)


def customer(_id):
    return _get(db.customers, _id)


def order_guide(_id):
    return _get(db.order_guides, _id)


def order_guide_item(_id):
    return _get(db.order_guide_items, _id)


def inventory_lot(_id):
    return _get(db.inventory_lots, _id)


def order(_id):
    return _get(db.orders, _id)


def order_line(_id):
    return _get(db.order_lines, _id)


def shipment(_id):
    return _get(db.shipments, _id)


def return_(_id):
    return _get(db.returns, _id)


def lines_of_order(order_id):
    """All OrderLine records for an order, sorted created_at ASC."""
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: l["created_at"])
    return lines
