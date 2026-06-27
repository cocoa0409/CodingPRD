"""Shared route helpers: fetch-or-404, structural validation, list pagination/sort."""

from errors import err
from middleware import parse_pagination
from models import serialize


def fetch_or_404(collection, entity_id):
    obj = collection.get(entity_id)
    if obj is None:
        raise err("ERR_NOT_FOUND", "Resource %s not found." % entity_id)
    return obj


def require_fields(body, fields):
    """Priority 5 — required fields present (PRD §2.9)."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_int(body, field, minimum=None, maximum=None, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer." % field)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (field, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be <= %s." % (field, maximum))
    return val


def require_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string." % field)
    return val


def require_bool(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return None
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean." % field)
    return val


def require_enum(body, field, domain, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
        return default
    val = body[field]
    if val not in domain:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (field, sorted(domain)))
    return val


def list_response(items, sort_seq=True):
    """Sort by creation order ASC (PRD §2.3), paginate, return (page, pagination)."""
    limit, offset = parse_pagination()
    if sort_seq:
        items = sorted(items, key=lambda o: o["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return [serialize(o) for o in page], pagination
