"""Shared route helpers: account-subtree resolution per resource kind,
list responses, and common lookups."""

from flask import request

from db import db
from response import success_list
from validate import paginate, cc_scope


def account_of_account(a):
    return a["id"]


def account_of_asset(a):
    return a["account_id"]


def account_of_design(d):
    asset = db["assets"].get(d["asset_id"])
    return asset["account_id"] if asset else None


def account_of_station(s):
    asset = db["assets"].get(s["asset_id"])
    return asset["account_id"] if asset else None


def account_of_reading(r):
    station = db["feed_stations"].get(r["station_id"])
    return account_of_station(station) if station else None


def account_of_route(r):
    return r["account_id"]


def account_of_stop(s):
    route = db["test_routes"].get(s["route_id"])
    return route["account_id"] if route else None


def account_of_result(r):
    asset = db["assets"].get(r["asset_id"])
    return asset["account_id"] if asset else None


def account_of_action(a):
    asset = db["assets"].get(a["asset_id"])
    return asset["account_id"] if asset else None


def account_of_rack(r):
    asset = db["assets"].get(r["asset_id"])
    return asset["account_id"] if asset else None


def account_of_coupon(c):
    rack = db["coupon_racks"].get(c["rack_id"])
    return account_of_rack(rack) if rack else None


def account_of_plan(p):
    asset = db["assets"].get(p["asset_id"])
    return asset["account_id"] if asset else None


def account_of_blowdown(b):
    asset = db["assets"].get(b["asset_id"])
    return asset["account_id"] if asset else None


def account_of_order(o):
    return o["account_id"]


def account_of_invoice(i):
    return i["account_id"]


def list_response(items, serializer, account_of=None, user=None):
    """Sort by created_at ASC (stable on insertion seq), scope for
    CustomerContact, filter, paginate, and wrap in the envelope."""
    role, user_id = user
    items = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    if account_of is not None:
        items = cc_scope(role, user_id, items, account_of)
    page, limit, offset, total = paginate(items)
    return success_list([serializer(e) for e in page], limit, offset, total)


def query_filter(name):
    return request.args.get(name)
