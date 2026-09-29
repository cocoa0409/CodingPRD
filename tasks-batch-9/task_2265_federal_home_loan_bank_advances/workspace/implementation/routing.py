"""Route registration, authentication guard and path-lookup helpers."""

from functools import wraps

from flask import g, request

import config
from errors import ApiError
from store import db

ROUTES = []


def endpoint(rule, methods, roles):
    """Declare a route; ``roles`` is the exact set permitted on it."""

    def decorator(fn):
        ROUTES.append((rule, tuple(methods), tuple(roles), fn))
        return fn

    return decorator


def _guard(roles, fn):
    @wraps(fn)
    def wrapper(**kwargs):
        user_id = request.headers.get("X-User-ID")
        role = request.headers.get("X-User-Role")
        if not user_id or not role or role not in config.ALL_ROLES:
            raise ApiError("ERR_UNAUTHENTICATED")
        if role not in roles:
            raise ApiError("ERR_UNAUTHORIZED")
        g.user_id = user_id
        g.role = role
        return fn(**kwargs)

    return wrapper


def register_all(app):
    for rule, methods, roles, fn in ROUTES:
        app.add_url_rule(
            rule,
            endpoint="%s.%s" % (fn.__module__, fn.__name__),
            view_func=_guard(roles, fn),
            methods=list(methods),
        )


# ------------------------------------------------------------------- lookups --


def _find(collection, entity_id, error_id):
    record = collection.get(entity_id)
    if record is None:
        raise ApiError(error_id)
    return record


def get_member(entity_id):
    return _find(db.members, entity_id, "ERR_MEMBER_BANK_NOT_FOUND")


def get_subscription(entity_id):
    return _find(db.subscriptions, entity_id, "ERR_STOCK_SUBSCRIPTION_NOT_FOUND")


def get_asset(entity_id):
    return _find(db.assets, entity_id, "ERR_COLLATERAL_ASSET_NOT_FOUND")


def get_receipt(entity_id):
    return _find(db.receipts, entity_id, "ERR_SAFEKEEPING_RECEIPT_NOT_FOUND")


def get_review(entity_id):
    return _find(db.reviews, entity_id, "ERR_REVIEW_NOT_FOUND")


def get_finding(entity_id):
    return _find(db.findings, entity_id, "ERR_REVIEW_FINDING_NOT_FOUND")


def get_product(entity_id):
    return _find(db.products, entity_id, "ERR_ADVANCE_PRODUCT_NOT_FOUND")


def get_advance(entity_id):
    return _find(db.advances, entity_id, "ERR_ADVANCE_NOT_FOUND")


def get_prepayment(entity_id):
    return _find(db.prepayments, entity_id, "ERR_PREPAYMENT_EVENT_NOT_FOUND")


def get_allocation(entity_id):
    return _find(db.allocations, entity_id, "ERR_ALLOCATION_NOT_FOUND")
