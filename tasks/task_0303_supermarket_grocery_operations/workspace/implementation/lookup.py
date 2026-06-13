"""Entity lookup helpers that raise the correct not-found error."""
from db import db
from errors import (
    ApiError,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND,
    ERR_SHIPMENT_LINE_NOT_FOUND,
    ERR_PRICE_PLAN_NOT_FOUND,
    ERR_PROMOTION_NOT_FOUND,
    ERR_MEMBER_NOT_FOUND,
    ERR_COUPON_NOT_FOUND,
    ERR_CLIPPED_COUPON_NOT_FOUND,
    ERR_SALE_NOT_FOUND,
    ERR_LINE_ITEM_NOT_FOUND,
    ERR_CYCLE_COUNT_NOT_FOUND,
    ERR_EOD_NOT_FOUND,
)


def _get(store, key, spec):
    rec = store.get(key)
    if rec is None:
        raise ApiError(spec[0], spec[1], f"{spec[0]}")
    return rec


def get_department(did):
    return _get(db.departments, did, ERR_DEPARTMENT_NOT_FOUND)


def get_product(pid):
    return _get(db.products, pid, ERR_PRODUCT_NOT_FOUND)


def get_lot(lid):
    return _get(db.inventory_lots, lid, ERR_LOT_NOT_FOUND)


def get_shipment(sid):
    return _get(db.shipments, sid, ERR_SHIPMENT_NOT_FOUND)


def get_shipment_line(lid):
    return _get(db.shipment_lines, lid, ERR_SHIPMENT_LINE_NOT_FOUND)


def get_price_plan(pid):
    return _get(db.price_plans, pid, ERR_PRICE_PLAN_NOT_FOUND)


def get_promotion(pid):
    return _get(db.promotions, pid, ERR_PROMOTION_NOT_FOUND)


def get_member(mid):
    return _get(db.members, mid, ERR_MEMBER_NOT_FOUND)


def get_coupon(cid):
    return _get(db.coupons, cid, ERR_COUPON_NOT_FOUND)


def get_clip(cid):
    return _get(db.clipped_coupons, cid, ERR_CLIPPED_COUPON_NOT_FOUND)


def get_sale(sid):
    return _get(db.sales, sid, ERR_SALE_NOT_FOUND)


def get_sale_line(lid):
    return _get(db.sale_line_items, lid, ERR_LINE_ITEM_NOT_FOUND)


def get_cycle_count(cid):
    return _get(db.cycle_counts, cid, ERR_CYCLE_COUNT_NOT_FOUND)


def get_eod(eid):
    return _get(db.eod_reconciliations, eid, ERR_EOD_NOT_FOUND)
