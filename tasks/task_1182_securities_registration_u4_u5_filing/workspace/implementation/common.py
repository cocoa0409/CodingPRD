"""Shared route helpers: body parsing, existence checks, validation, pagination, serialization."""
from datetime import datetime

from flask import request

from db import store, new_id
from timeutil import now
from errors import err_not_found, err_invalid_request


def body():
    """Parsed JSON object body; malformed/absent JSON treated as empty object."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def get_or_404(coll, entity_id):
    ent = coll.get(entity_id)
    if ent is None:
        raise err_not_found()
    return ent


def fk_or_404(coll, value):
    """Body-FK existence check; only runs when the value is present."""
    if value is None:
        return None
    return get_or_404(coll, value)


def required(data, field):
    v = data.get(field)
    if v is None:
        raise err_invalid_request(f"{field} is required")
    return v


def require_enum(value, allowed, field):
    if not isinstance(value, str) or value not in allowed:
        raise err_invalid_request(f"{field} must be one of {sorted(allowed)}")
    return value


def require_min_len(value, n, field):
    if not isinstance(value, str) or len(value) < n:
        raise err_invalid_request(f"{field} must be a string of at least {n} characters")
    return value


def new_entity():
    ts = now()
    store.seq += 1
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.seq,
    }


def touch(ent):
    """Every mutation refreshes updated_at and increments version."""
    ent["version"] += 1
    ent["updated_at"] = now()


def serialize(ent, computed=None):
    from timeutil import fmt
    out = {}
    for k, v in ent.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt(v)
        else:
            out[k] = v
    if computed:
        out.update(computed)
    return out


def pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise err_invalid_request("limit and offset must be integers")
    if isinstance(limit, bool) or isinstance(offset, bool):
        raise err_invalid_request("limit and offset must be integers")
    if limit < 1 or limit > 100:
        raise err_invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise err_invalid_request("offset must be >= 0")
    return limit, offset


def list_page(coll, filter_spec=()):
    """filter_spec: tuple of (query_param, record_key, converter)."""
    items = sorted(coll.values(), key=lambda e: (e["created_at"], e["_seq"]))
    for param, key, conv in filter_spec:
        raw = request.args.get(param)
        if raw is None:
            continue
        if conv is int:
            try:
                val = int(raw)
            except ValueError:
                raise err_invalid_request(f"{param} must be an integer")
        else:
            val = raw
        items = [e for e in items if e.get(key) == val]
    limit, offset = pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
