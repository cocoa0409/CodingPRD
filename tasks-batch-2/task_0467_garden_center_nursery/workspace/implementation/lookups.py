"""Existence lookups (priority 3 path resolution) + body helpers."""
from flask import request

import errors
from db import db
from errors import err, ApiError


def body():
    """Parse JSON body; tolerate empty / missing body as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err(errors.ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def get_nursery(nursery_id):
    n = db.nurseries.get(nursery_id)
    if n is None:
        err(errors.ERR_NURSERY_NOT_FOUND, "nursery not found")
    return n


def get_account(account_id):
    a = db.accounts.get(account_id)
    if a is None:
        err(errors.ERR_ACCOUNT_NOT_FOUND, "account not found")
    return a


def get_product(product_id):
    p = db.products.get(product_id)
    if p is None:
        err(errors.ERR_PRODUCT_NOT_FOUND, "product not found")
    return p


def get_order(order_id):
    o = db.orders.get(order_id)
    if o is None:
        err(errors.ERR_ORDER_NOT_FOUND, "order not found")
    return o


def get_order_line(line_id):
    ol = db.order_lines.get(line_id)
    if ol is None:
        err(errors.ERR_LINE_NOT_FOUND, "order line not found")
    return ol


def get_lot(lot_id):
    lot = db.inventory_lots.get(lot_id)
    if lot is None:
        err(errors.ERR_LOT_NOT_FOUND, "inventory lot not found")
    return lot


def get_special_order(so_id):
    so = db.special_orders.get(so_id)
    if so is None:
        err(errors.ERR_SPECIAL_ORDER_NOT_FOUND, "special order not found")
    return so


def get_delivery(delivery_id):
    d = db.deliveries.get(delivery_id)
    if d is None:
        err(errors.ERR_DELIVERY_NOT_FOUND, "delivery not found")
    return d


def get_vehicle(vehicle_id):
    v = db.vehicles.get(vehicle_id)
    if v is None:
        err(errors.ERR_VEHICLE_NOT_FOUND, "vehicle not found")
    return v


def get_claim(claim_id):
    c = db.warranty_claims.get(claim_id)
    if c is None:
        err(errors.ERR_CLAIM_NOT_FOUND, "warranty claim not found")
    return c
