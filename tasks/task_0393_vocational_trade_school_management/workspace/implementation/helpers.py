"""Shared helpers: input validation, pagination, version bumps, serialization."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store, now_ts, new_id
from errors import err

# Internal-only keys never serialized to clients.
_INTERNAL_KEYS = {"_seq"}


def get_json_body():
    """Parse JSON body; return {} when absent. Reject malformed JSON."""
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            body = request.get_json(force=True, silent=True)
        except Exception:
            body = None
        if body is None:
            # Empty body is acceptable for parameterless transitions.
            if not request.data or request.data.strip() == b"":
                return {}
            raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        if not isinstance(body, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return body
    return {}


def serialize(entity):
    """Strip internal keys for the response."""
    return {k: v for k, v in entity.items() if k not in _INTERNAL_KEYS}


def stamp_new(entity):
    """Attach id/created_at/updated_at/version/_seq for a new entity."""
    ts = now_ts()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = store.next_seq()
    return entity


def bump(entity):
    """Mutation bump: refresh updated_at, increment version."""
    entity["updated_at"] = now_ts()
    entity["version"] = entity.get("version", 1) + 1
    return entity


# --------------------------------------------------------------------------
# Input validation primitives. Raise ERR_INVALID_REQUEST (400) on failure.
# --------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def as_int(body, name, required=True, minimum=None, maximum=None, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (name, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s." % (name, maximum))
    return val


def as_number(body, name, required=True, minimum=None, maximum=None,
              exclusive_min=None, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number." % name)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (name, minimum))
    if exclusive_min is not None and val <= exclusive_min:
        raise err("ERR_INVALID_REQUEST", "Field %s must be > %s." % (name, exclusive_min))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s." % (name, maximum))
    return val


def as_str(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if not isinstance(val, str) or val.strip() == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string." % name)
    return val


def as_bool(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % name)
    return val


def as_enum(body, name, allowed, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
        return default
    val = body[name]
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "Field %s must be one of %s." % (name, sorted(allowed)))
    return val


# --------------------------------------------------------------------------
# Pagination per PRD §2.3
# --------------------------------------------------------------------------
def paginate(items):
    """Apply limit/offset query params; return (page, pagination_meta).

    items: list already sorted by created_at ascending.
    """
    limit = _parse_pagination_int("limit", default=10, minimum=1, maximum=100)
    offset = _parse_pagination_int("offset", default=0, minimum=0, maximum=None)
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta


def _parse_pagination_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "Query param %s must be an integer." % name)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Query param %s must be >= %s." % (name, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "Query param %s must be <= %s." % (name, maximum))
    return val


def sorted_collection(collection_dict, predicate=None):
    """Return entities sorted by creation order (created_at asc, tie-break _seq)."""
    items = [e for e in collection_dict.values() if predicate is None or predicate(e)]
    items.sort(key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
    return items


# --------------------------------------------------------------------------
# Existence lookups. Raise ERR_NOT_FOUND (404).
# --------------------------------------------------------------------------
def find_or_404(collection_dict, entity_id, label="resource"):
    ent = collection_dict.get(entity_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "%s not found." % label)
    return ent


# --------------------------------------------------------------------------
# Monetary rounding: sum-then-round, ROUND_HALF_UP, once.
# --------------------------------------------------------------------------
def round_half_up_cents(amount_decimal):
    """Round a Decimal amount to a whole integer of cents (half-up)."""
    return int(Decimal(amount_decimal).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4(value):
    """Round to 4 decimal places, half-up, returning a float."""
    q = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)
