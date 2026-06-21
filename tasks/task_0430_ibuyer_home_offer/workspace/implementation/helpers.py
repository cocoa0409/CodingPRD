"""Shared route helpers: existence lookups, pagination, ownership, datetime parse."""

import datetime

from flask import request

from db import store
from errors import err
from validators import get_body  # re-export for convenience


# ---- existence lookups (ERR_NOT_FOUND, priority 3) ----
def get_seller_or_404(seller_id):
    rec = store.sellers.get(seller_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Seller not found")
    return rec


def get_property_or_404(prop_id):
    rec = store.properties.get(prop_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Property not found")
    return rec


def get_offer_or_404(offer_id):
    rec = store.offers.get(offer_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Offer not found")
    return rec


def get_assessment_or_404(assessment_id):
    rec = store.assessments.get(assessment_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Assessment not found")
    return rec


def get_transaction_or_404(tx_id):
    rec = store.transactions.get(tx_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Transaction not found")
    return rec


def get_resale_or_404(resale_id):
    rec = store.resales.get(resale_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resale not found")
    return rec


# ---- ownership (ERR_NOT_RESOURCE_OWNER, priority 4) ----
def require_property_owner(prop, role, user_id):
    """A Seller acting on a property/offer/transaction must own the property."""
    if role == "Seller" and prop["seller_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Seller does not own the underlying property")


# ---- pagination (PRD §2.3) ----
def pagination_params():
    """Parse limit/offset query params with defaults & bounds. Returns (limit, offset)."""
    limit = _parse_int_param("limit", default=10, minimum=1, maximum=100)
    offset = _parse_int_param("offset", default=0, minimum=0, maximum=None)
    return limit, offset


def _parse_int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except (ValueError, TypeError):
            value = default
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def paginate(records, limit, offset):
    """Sort ascending by created_at then slice. Returns (page, total_count)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---- datetime parse for body fields (ERR_INVALID_REQUEST on bad format) ----
def parse_datetime_field(value, name):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an ISO-8601 string" % name)
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO-8601 instant" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)
