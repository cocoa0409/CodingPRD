"""Shared route helpers."""
from decimal import Decimal

import calc
import db as store
import response
from db import db, flush
from errors import ApiError


def get_seller(seller_id):
    row = db.sellers.get(seller_id)
    if row is None:
        raise ApiError("ERR_SELLER_NOT_FOUND", 404)
    return row


def get_fc(fc_id):
    row = db.fcs.get(fc_id)
    if row is None:
        raise ApiError("ERR_FC_NOT_FOUND", 404)
    return row


def get_listing(listing_id):
    row = db.listings.get(listing_id)
    if row is None:
        raise ApiError("ERR_LISTING_NOT_FOUND", 404)
    return row


def get_plan(plan_id):
    row = db.plans.get(plan_id)
    if row is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", 404)
    return row


def get_lot(lot_id):
    row = db.lots.get(lot_id)
    if row is None:
        raise ApiError("ERR_LOT_NOT_FOUND", 404)
    return row


def get_removal(removal_id):
    row = db.removals.get(removal_id)
    if row is None:
        raise ApiError("ERR_REMOVAL_ORDER_NOT_FOUND", 404)
    return row


def get_claim(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404)
    return row


def listing_seller(listing):
    return get_seller(listing["seller_account_id"])


def lot_listing(lot):
    return get_listing(lot["sku_listing_id"])


def finish(payload, status=200):
    """Reconcile derived fields, stamp mutations and answer."""
    calc.recompute_all()
    flush()
    return response.object_response(payload(), status)


def listing_page(rows, serializer, args):
    limit, offset = response.page_params(args)
    page, total = response.paginate(rows, limit, offset)
    return response.array_response([serializer(r) for r in page], limit, offset, total)


def filter_eq(rows, args, field, param=None):
    value = args.get(param or field)
    if value is None or value == "":
        return rows
    return [r for r in rows if str(r.get(field)) == value]
