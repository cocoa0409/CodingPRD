"""Existence resolution, field-shape validation, and list helpers.

PRD 2.5 / 3.10: path identifiers resolved first, then body foreign keys
left-to-right; any missing reference -> ERR_NOT_FOUND (404). A missing receipt
id -> ERR_RECEIPT_NOT_FOUND (404).
"""
from db import db
from errors import err


def get_or_404(collection, entity_id):
    entity = collection.get(entity_id)
    if entity is None:
        raise err("ERR_NOT_FOUND")
    return entity


def get_receipt_or_404(receipt_id):
    receipt = db.receipts.get(receipt_id)
    if receipt is None:
        raise err("ERR_RECEIPT_NOT_FOUND")
    return receipt


def require_fields(body, names):
    """Each named field must be present and non-null -> else ERR_INVALID_REQUEST (400)."""
    for name in names:
        if body.get(name) is None:
            raise err("ERR_INVALID_REQUEST")


def require_string(body, name):
    require_fields(body, [name])
    value = body.get(name)
    if not isinstance(value, str) or not value.strip():
        raise err("ERR_INVALID_REQUEST")
    return value


def require_enum(body, name, allowed):
    value = body.get(name)
    if value is None or value not in allowed:
        raise err("ERR_INVALID_REQUEST")
    return value


def optional_enum(body, name, allowed, default):
    if name not in body or body.get(name) is None:
        return default
    value = body.get(name)
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST")
    return value


def require_positive_int(body, name):
    """Required integer that must be > 0 (PRD 3.10: non-positive amount -> ERR_INVALID_REQUEST)."""
    value = body.get(name)
    if not _is_int(value):
        raise err("ERR_INVALID_REQUEST")
    value = int(value)
    if value <= 0:
        raise err("ERR_INVALID_REQUEST")
    return value


def require_int(body, name):
    value = body.get(name)
    if not _is_int(value):
        raise err("ERR_INVALID_REQUEST")
    return int(value)


def optional_int(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    value = body.get(name)
    if not _is_int(value):
        raise err("ERR_INVALID_REQUEST")
    return int(value)


def optional_nonneg_int(body, name, default):
    value = optional_int(body, name, default)
    if value < 0:
        raise err("ERR_INVALID_REQUEST")
    return value


def optional_bool(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    value = body.get(name)
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST")
    return value


def optional_string(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    value = body.get(name)
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST")
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def filtered_sorted(collection, filters):
    """Return collection values matching all (key,value) filters where value is
    not None, sorted by created_at ascending (via the stable _seq) (PRD 2.3)."""
    items = list(collection.values())
    for key, val in filters.items():
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    items.sort(key=lambda e: e["_seq"])
    return items
