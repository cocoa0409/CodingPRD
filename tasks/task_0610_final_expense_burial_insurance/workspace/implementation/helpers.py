"""Shared request/serialization helpers."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err


def get_body():
    """Return the JSON body as a dict (empty dict when none)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_VALIDATION", "Missing required field: %s" % f)


def serialize(entity):
    """Strip internal bookkeeping fields before emitting a resource."""
    if entity is None:
        return None
    out = {k: v for k, v in entity.items() if not k.startswith("_")}
    return out


def round_half_up(value):
    """Round a numeric value half-up to the nearest whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def paginate(items):
    """Apply limit/offset pagination (PRD §2.3).

    limit defaults 10, min 1, max 100. offset defaults 0. Returns
    (page_items, pagination_meta).
    """
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
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


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return default
    if minimum is not None and val < minimum:
        val = minimum
    if maximum is not None and val > maximum:
        val = maximum
    return val


def sort_by_created(items):
    """Sort by created_at ASC, breaking ties by insertion sequence (PRD §2.3)."""
    return sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
