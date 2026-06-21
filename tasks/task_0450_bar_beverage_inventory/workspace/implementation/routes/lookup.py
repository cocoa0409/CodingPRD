"""Shared resource lookup helpers. A missing resource raises ERR_NOT_FOUND
(404) per PRD §2.5; references are validated path-first then body FKs."""
from db import db
from errors import not_found


def get_product(pid):
    p = db.products.get(pid)
    if p is None:
        raise not_found("Product not found.")
    return p


def get_recipe(rid):
    r = db.recipes.get(rid)
    if r is None:
        raise not_found("Recipe not found.")
    return r


def get_menu_item(mid):
    m = db.menu_items.get(mid)
    if m is None:
        raise not_found("Menu item not found.")
    return m


def get_count_session(sid):
    s = db.count_sessions.get(sid)
    if s is None:
        raise not_found("Count session not found.")
    return s


def get_purchase_order(pid):
    po = db.purchase_orders.get(pid)
    if po is None:
        raise not_found("Purchase order not found.")
    return po


def get_invoice(iid):
    inv = db.invoices.get(iid)
    if inv is None:
        raise not_found("Invoice not found.")
    return inv
