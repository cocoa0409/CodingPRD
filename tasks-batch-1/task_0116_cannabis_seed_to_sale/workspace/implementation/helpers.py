"""Shared utilities: decimal rounding, pagination, request-body validation,
and resource mutation (version/updated_at bump)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import clock
from errors import err


# ----------------------------------------------------------------------------
# Decimal / rounding (PRD §2.9: 2dp, round-half-up).
# ----------------------------------------------------------------------------
def to_decimal(value):
    return Decimal(str(value))


def round2(value):
    """Round to 2 decimal places, round-half-up. Returns a float for JSON."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# ----------------------------------------------------------------------------
# Request body / query parsing.
# ----------------------------------------------------------------------------
def get_json_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return data
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3: limit default 10 min 1 max 100; offset default 0 min 0).
# ----------------------------------------------------------------------------
def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = 10
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    offset = 0
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0

    return limit, offset


def paginate(items):
    """items already filtered+sorted; returns (page, limit, offset, total)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total


def sort_by_created(items):
    # created_at ascending; ties broken by insertion order via id stability.
    return sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))


# ----------------------------------------------------------------------------
# Resource lifecycle helpers (PRD §2.4).
# ----------------------------------------------------------------------------
_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def stamp_create(record, versioned=True):
    ts = clock.now_iso()
    record["created_at"] = ts
    record["_seq"] = next_seq()
    if versioned:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Mutate a versioned resource: bump version + updated_at together."""
    record["version"] = record["version"] + 1
    record["updated_at"] = clock.now_iso()
