"""Existence lookups (priority-3 ERR_NOT_FOUND) and buyer-ownership checks.

Path identifiers are validated strictly left-to-right; the first that does not
resolve yields ERR_NOT_FOUND (PRD §2.4).
"""
import errors
from db import store


def _get(collection, _id):
    rec = collection.get(_id)
    if rec is None:
        raise errors.not_found()
    return rec


def get_tier(_id):
    return _get(store.price_tiers, _id)


def get_account(_id):
    return _get(store.accounts, _id)


def get_profile(_id):
    return _get(store.roast_profiles, _id)


def get_product(_id):
    return _get(store.products, _id)


def get_green_lot(_id):
    return _get(store.green_lots, _id)


def get_batch(_id):
    return _get(store.roast_batches, _id)


def get_roasted_lot(_id):
    return _get(store.roasted_lots, _id)


def get_standing_order(_id):
    return _get(store.standing_orders, _id)


def get_order(_id):
    return _get(store.orders, _id)


def get_fulfillment(_id):
    return _get(store.fulfillments, _id)


def get_sample_request(_id):
    return _get(store.sample_requests, _id)


def get_invoice(_id):
    return _get(store.invoices, _id)


# --------------------------------------------------------------------------
# Buyer ownership (PRD §2.1): a WholesaleBuyer's X-User-ID is its account id.
# It may only act on resources whose owning account == X-User-ID.
# --------------------------------------------------------------------------
def assert_buyer_owns_account(role, user_id, account_id):
    if role == "WholesaleBuyer" and user_id != account_id:
        raise errors.forbidden()
