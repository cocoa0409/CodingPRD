"""Shared validation/lookup helpers, used across routes in validation-priority order."""
from decimal import Decimal, ROUND_HALF_UP

from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ENUM,
)
from db import db


def round_half_up(value):
    """Round a numeric value to the nearest integer, half away from zero (up)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- existence lookups (priority 4) ---

def get_or_404(table, _id):
    ent = table.get(_id)
    if ent is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return ent


def find_customer(_id):
    return get_or_404(db.customers, _id)


def find_sku(_id):
    return get_or_404(db.skus, _id)


def find_lot(_id):
    return get_or_404(db.lots, _id)


def find_subscription(_id):
    return get_or_404(db.subscriptions, _id)


def find_order(_id):
    return get_or_404(db.orders, _id)


def find_order_line(_id):
    return get_or_404(db.order_lines, _id)


def find_bulk_quote(_id):
    return get_or_404(db.bulk_quotes, _id)


def find_referral(_id):
    return get_or_404(db.referrals, _id)


def find_winback(_id):
    return get_or_404(db.winback_offers, _id)


# --- request-shape validation (priority 5) ---

def body():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def require_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return v


def require_int(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    return v


# --- enum validation (priority 6) ---

ZONES = {"Z1", "Z2", "Z3", "Z4"}
CATEGORIES = {"HOT_SAUCE", "COFFEE", "SNACK"}
STORAGE_CLASSES = {"AMBIENT", "PERISHABLE"}
TIERS = {"STARTER", "CLASSIC", "RESERVE"}
CADENCES = {14, 28, 56}
ORDER_KINDS = {"ONE_TIME", "SUBSCRIPTION", "GIFT", "CORPORATE_BULK"}
ALLERGENS = {"MILK", "EGG", "FISH", "SHELLFISH", "TREE_NUT", "PEANUT", "WHEAT", "SOY", "SESAME"}


def require_enum(value, domain, label):
    if value not in domain:
        raise err(ERR_INVALID_ENUM, f"Invalid {label}: {value}")
    return value


# --- pagination ---

def paginate(items, args):
    """items: list already sorted. Returns (page, limit, offset, total)."""
    total = len(items)
    limit = args.get("limit", 10)
    offset = args.get("offset", 0)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return items[offset:offset + limit], limit, offset, total


def sorted_by_created(entities):
    return sorted(entities, key=lambda e: e["_seq"])
