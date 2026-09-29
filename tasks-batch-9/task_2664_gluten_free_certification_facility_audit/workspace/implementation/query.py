"""Lookup and pagination helpers."""

from flask import request

import db
import response
from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import ApiError

_TABLES = {
    "applicant": (lambda: db.applicants, "ERR_APPLICANT_NOT_FOUND"),
    "facility": (lambda: db.facilities, "ERR_FACILITY_NOT_FOUND"),
    "supplier": (lambda: db.suppliers, "ERR_SUPPLIER_NOT_FOUND"),
    "supplier_document": (lambda: db.supplier_documents,
                          "ERR_SUPPLIER_DOCUMENT_NOT_FOUND"),
    "ingredient": (lambda: db.ingredients, "ERR_INGREDIENT_NOT_FOUND"),
    "product": (lambda: db.products, "ERR_PRODUCT_NOT_FOUND"),
    "product_ingredient": (lambda: db.product_ingredients,
                           "ERR_PRODUCT_INGREDIENT_NOT_FOUND"),
    "lot_test": (lambda: db.lot_tests, "ERR_LOT_TEST_NOT_FOUND"),
    "audit": (lambda: db.audits, "ERR_AUDIT_NOT_FOUND"),
    "certificate": (lambda: db.certificates, "ERR_CERTIFICATE_NOT_FOUND"),
    "nonconformance": (lambda: db.nonconformances, "ERR_NONCONFORMANCE_NOT_FOUND"),
    "change_notification": (lambda: db.change_notifications,
                            "ERR_CHANGE_NOTIFICATION_NOT_FOUND"),
    "complaint": (lambda: db.consumer_complaints, "ERR_COMPLAINT_NOT_FOUND"),
}


def fetch(kind, row_id):
    table_fn, error_id = _TABLES[kind]
    if not isinstance(row_id, str):
        raise ApiError(error_id)
    row = table_fn().get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def maybe(kind, row_id):
    if row_id is None:
        return None
    return fetch(kind, row_id)


def _page_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be an integer." % name)
    if value < minimum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be <= %d." % (name, maximum))
    return value


def paginate(rows):
    limit = _page_int("limit", PAGINATION_DEFAULT_LIMIT,
                      PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _page_int("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def listing(table, filters=None):
    """Sorted, filtered, paginated collection response."""
    rows = db.ordered(table)
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            rows = [r for r in rows if _matches(r.get(field), value)]
    page, meta = paginate(rows)
    return response.collection([response.serialize(r) for r in page], meta)


def _matches(stored, wanted):
    if isinstance(stored, bool):
        return _as_bool(wanted) is stored
    if stored is None:
        return False
    return str(stored) == str(wanted)


def _as_bool(raw):
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "1", "yes")


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
