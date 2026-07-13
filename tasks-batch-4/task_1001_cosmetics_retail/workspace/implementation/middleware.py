"""Auth, payload-shape validation, pagination and path lookups.

Validation precedence (PRD 2.9):
  1 auth -> 2 authorisation -> 3 path existence -> 4 payload shape
  -> 5 body-reference existence -> 6 ownership -> 7 state -> 8 OCC -> business rules
"""
from flask import request

from db import db, in_creation_order
from errors import ApiError, invalid
from util import parse_dt

ROLES = ("Customer", "StoreAssociate", "BeautyArtist", "MerchandisingAdmin")


class Auth(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_customer(self):
        return self.role == "Customer"


def authenticate(*allowed_roles):
    """Steps 1 and 2 of the precedence chain."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and a valid X-User-Role header are required")
    auth = Auth(user_id, role)
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    return auth


# --------------------------------------------------------------------------
# payload shape helpers (step 4 -> ERR_INVALID_REQUEST / 400)
# --------------------------------------------------------------------------

def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise invalid("request body must be a JSON object")
    return payload


def required(payload, key):
    if key not in payload or payload[key] is None:
        raise invalid("'%s' is required" % key)
    return payload[key]


def as_int(value, key, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("'%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        raise invalid("'%s' must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("'%s' must be <= %s" % (key, maximum))
    return value


def as_number(value, key, minimum=None, maximum=None, exclusive_max=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("'%s' must be a number" % key)
    if minimum is not None and value < minimum:
        raise invalid("'%s' must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("'%s' must be <= %s" % (key, maximum))
    if exclusive_max is not None and value >= exclusive_max:
        raise invalid("'%s' must be < %s" % (key, exclusive_max))
    return value


def as_bool(value, key):
    if not isinstance(value, bool):
        raise invalid("'%s' must be a boolean" % key)
    return value


def as_str(value, key):
    if not isinstance(value, str) or not value.strip():
        raise invalid("'%s' must be a non-empty string" % key)
    return value


def as_enum(value, key, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise invalid("'%s' must be one of %s" % (key, ", ".join(sorted(allowed))))
    return value


def as_dt(value, key):
    parsed = parse_dt(value)
    if parsed is None:
        raise invalid("'%s' must be an ISO 8601 datetime" % key)
    return parsed


def opt(payload, key, default=None):
    value = payload.get(key)
    return default if value is None else value


# --------------------------------------------------------------------------
# pagination (PRD 2.3)
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    raw_limit = args.get("limit", "10")
    raw_offset = args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise invalid("'limit' must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise invalid("'offset' must be an integer")
    if limit < 1 or limit > 100:
        raise invalid("'limit' must be between 1 and 100")
    if offset < 0:
        raise invalid("'offset' must be >= 0")
    return limit, offset


def page(records, limit, offset, serializer):
    ordered = in_creation_order(records)
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return [serializer(r) for r in window], total


# --------------------------------------------------------------------------
# lookups (steps 3 and 5)
# --------------------------------------------------------------------------

def _get(table, key, error_id):
    record = table.get(key)
    if record is None:
        raise ApiError(error_id, "%s does not resolve" % key)
    return record


def get_store(store_id):
    return _get(db.stores, store_id, "ERR_STORE_NOT_FOUND")


def get_product(product_id):
    return _get(db.products, product_id, "ERR_PRODUCT_NOT_FOUND")


def get_variant(variant_id):
    return _get(db.variants, variant_id, "ERR_VARIANT_NOT_FOUND")


def get_lot(lot_id):
    return _get(db.lots, lot_id, "ERR_LOT_NOT_FOUND")


def get_customer(customer_id):
    return _get(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")


def get_promotion(promotion_id):
    return _get(db.promotions, promotion_id, "ERR_PROMOTION_NOT_FOUND")


def get_order(order_id):
    return _get(db.orders, order_id, "ERR_ORDER_NOT_FOUND")


def get_order_line(line_id):
    return _get(db.order_lines, line_id, "ERR_ORDER_LINE_NOT_FOUND")


def get_artist(artist_id):
    return _get(db.artists, artist_id, "ERR_ARTIST_NOT_FOUND")


def get_booking(booking_id):
    return _get(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")


def get_return(return_id):
    return _get(db.returns, return_id, "ERR_RETURN_NOT_FOUND")


def get_ledger_entry(entry_id):
    entry = db.ledger.get(entry_id)
    if entry is None:
        raise ApiError("ERR_NOT_FOUND", "%s does not resolve" % entry_id)
    return entry


# --------------------------------------------------------------------------
# ownership (step 6)
# --------------------------------------------------------------------------

def own_customer(auth, customer_id):
    """A Customer may only touch resources whose customer_id is their X-User-ID."""
    if auth.is_customer and auth.user_id != customer_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", "this resource belongs to another customer")


def own_artist(auth, artist_id):
    """A BeautyArtist may only act on bookings that name them (PRD 2.1)."""
    if auth.role == "BeautyArtist" and auth.user_id != artist_id:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", "this booking belongs to another artist")
