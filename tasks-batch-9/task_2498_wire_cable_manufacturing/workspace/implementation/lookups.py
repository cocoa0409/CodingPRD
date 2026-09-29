"""Reference resolution (PRD 2.10) — one helper per not-found code."""

import errors
from db import db


def _get(collection, ident, spec):
    if not isinstance(ident, str):
        errors.fail(spec, "Reference must be a string identifier")
    rec = collection.get(ident)
    if rec is None:
        errors.fail(spec, "Referenced resource %s does not exist" % ident)
    return rec


def rod_lot(ident):
    return _get(db.rod_purchase_lots, ident, errors.ERR_ROD_LOT_NOT_FOUND)


def product(ident):
    return _get(db.catalog_products, ident, errors.ERR_PRODUCT_NOT_FOUND)


def order(ident):
    return _get(db.customer_orders, ident, errors.ERR_ORDER_NOT_FOUND)


def lot(ident):
    return _get(db.production_lots, ident, errors.ERR_LOT_NOT_FOUND)


def reel(ident):
    return _get(db.reels, ident, errors.ERR_REEL_NOT_FOUND)


def shipment(ident):
    return _get(db.shipments, ident, errors.ERR_SHIPMENT_NOT_FOUND)


def customer(ident):
    return _get(db.customers, ident, errors.ERR_CUSTOMER_NOT_FOUND)


def compound(ident):
    return _get(db.compounds, ident, errors.ERR_COMPOUND_NOT_FOUND)


def certification(ident):
    return _get(db.listing_certifications, ident, errors.ERR_CERTIFICATION_NOT_FOUND)
