"""Request parsing, validation, pagination, FK-existence helpers."""
from flask import request

from db import db
from errors import err

ALLERGENS = {"DAIRY", "GLUTEN", "NUTS", "SOY", "EGG", "SHELLFISH"}


def body():
    if request.is_json:
        data = request.get_json(silent=True)
    else:
        data = None
    if data is None:
        # accept empty body for no-input endpoints; treat as {}
        if request.data and request.data.strip():
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_type(data, field, types):
    if field in data and data[field] is not None and not isinstance(data[field], types):
        raise err("ERR_INVALID_REQUEST", f"Field {field} has wrong type.")


def require_bool(data, field):
    if field in data and data[field] is not None and not isinstance(data[field], bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be boolean.")


def require_int(data, field):
    # bool is a subclass of int; reject it explicitly
    if field in data and data[field] is not None:
        v = data[field]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")


def require_str(data, field):
    if field in data and data[field] is not None and not isinstance(data[field], str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string.")


def validate_allergen_array(data, field):
    if field in data and data[field] is not None:
        v = data[field]
        if not isinstance(v, list):
            raise err("ERR_INVALID_REQUEST", f"Field {field} must be an array.")
        for tag in v:
            if not isinstance(tag, str) or tag not in ALLERGENS:
                raise err("ERR_INVALID_REQUEST", f"Invalid allergen tag: {tag}")


def validate_enum(data, field, allowed):
    if field in data and data[field] is not None:
        if data[field] not in allowed:
            raise err("ERR_INVALID_REQUEST", f"Field {field} value not allowed.")


# ----- FK existence (ERR_NOT_FOUND) -----
_COLLECTIONS = {
    "store": "stores",
    "menu_item": "menu_items",
    "modifier": "modifiers",
    "pickup_slot": "pickup_slots",
    "customer": "customers",
    "loyalty_account": "loyalty_accounts",
    "points_ledger_entry": "points_ledger_entries",
    "subscription_plan": "subscription_plans",
    "subscription": "subscriptions",
    "order": "orders",
    "order_line": "order_lines",
    "loyalty_challenge": "loyalty_challenges",
}


def get_or_404(kind, entity_id):
    coll = getattr(db, _COLLECTIONS[kind])
    if not isinstance(entity_id, str) or entity_id not in coll:
        raise err("ERR_NOT_FOUND", f"{kind} not found.")
    return coll[entity_id]


def fk_or_404(kind, entity_id):
    """Validate an FK reference exists; None passes (optional FK)."""
    if entity_id is None:
        return None
    return get_or_404(kind, entity_id)


# ----- pagination -----
def pagination_params():
    limit = request.args.get("limit", None)
    offset = request.args.get("offset", None)
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """items: list already filtered. Returns (page, pagination_meta)."""
    limit, offset = pagination_params()
    # sort by creation order ascending (PRD §2.3)
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


def filter_by(collection, **filters):
    """Return list of entities matching all provided (non-None) filters."""
    out = []
    for e in collection.values():
        ok = True
        for k, v in filters.items():
            if v is not None and e.get(k) != v:
                ok = False
                break
        if ok:
            out.append(e)
    return out
