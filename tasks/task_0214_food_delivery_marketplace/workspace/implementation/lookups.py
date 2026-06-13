"""Existence lookups that raise the correct per-resource not-found error
(PRD §2.6). Validate path identifiers left to right, then body FKs.
"""
import errors
from db import store


def get_zone(zone_id):
    z = store.zones.get(zone_id)
    if z is None:
        raise errors.err(errors.ERR_ZONE_NOT_FOUND)
    return z


def get_restaurant(rid):
    r = store.restaurants.get(rid)
    if r is None:
        raise errors.err(errors.ERR_RESTAURANT_NOT_FOUND)
    return r


def get_menu_item(mid):
    m = store.menu_items.get(mid)
    if m is None:
        raise errors.err(errors.ERR_MENU_ITEM_NOT_FOUND)
    return m


def get_customer(cid):
    c = store.customers.get(cid)
    if c is None:
        raise errors.err(errors.ERR_CUSTOMER_NOT_FOUND)
    return c


def get_dasher(did):
    d = store.dashers.get(did)
    if d is None:
        raise errors.err(errors.ERR_DASHER_NOT_FOUND)
    return d


def get_order(oid):
    o = store.orders.get(oid)
    if o is None:
        raise errors.err(errors.ERR_ORDER_NOT_FOUND)
    return o


def get_line_item(lid):
    li = store.line_items.get(lid)
    if li is None:
        raise errors.err(errors.ERR_LINE_ITEM_NOT_FOUND)
    return li


def get_delivery(did):
    d = store.deliveries.get(did)
    if d is None:
        raise errors.err(errors.ERR_DELIVERY_NOT_FOUND)
    return d


def get_order_issue(iid):
    i = store.order_issues.get(iid)
    if i is None:
        raise errors.err(errors.ERR_ISSUE_NOT_FOUND)
    return i


def get_earnings_record(eid):
    e = store.earnings_records.get(eid)
    if e is None:
        raise errors.err(errors.ERR_EARNINGS_NOT_FOUND)
    return e
