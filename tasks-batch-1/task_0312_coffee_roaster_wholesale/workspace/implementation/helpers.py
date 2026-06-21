"""Shared helpers: body parsing, pagination, numeric/decimal rounding, common fields.

Money is integer cents. Weights are kg carried to 3 decimals, rounded HALF_UP
(PRD §2.5). All rounding uses decimal.Decimal with ROUND_HALF_UP — never float.
"""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from db import store, iso_z


# --------------------------------------------------------------------------
# Body parsing
# --------------------------------------------------------------------------
def get_body():
    """Return the JSON body as a dict, or {} for an empty body.

    Malformed JSON -> ERR_INVALID_REQUEST. A non-object JSON value (list, scalar)
    is also an invalid request for our write endpoints.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


# --------------------------------------------------------------------------
# Field validation helpers
# --------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request(f"Missing required field: {n}")


def as_int(value, field):
    # bool is a subclass of int; reject it explicitly
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number")
    return value


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return value


def require_positive_number(value, field):
    n = as_number(value, field)
    if n <= 0:
        raise errors.invalid_request(f"Field {field} must be greater than zero")
    return n


# --------------------------------------------------------------------------
# Decimal / rounding
# --------------------------------------------------------------------------
def D(value):
    return Decimal(str(value))


def round_kg(value):
    """Round to 3 decimals HALF_UP, return float."""
    q = D(value).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(q)


def round_cents(value):
    """Round to integer cents HALF_UP, return int."""
    q = D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def clamp_kg(value):
    """Round to 3 decimals HALF_UP, clamp at zero."""
    r = round_kg(value)
    return r if r > 0 else 0.0


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# --------------------------------------------------------------------------
def parse_pagination():
    limit = _parse_int_param("limit", default=10)
    offset = _parse_int_param("offset", default=0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset: offset + limit]
    return page, total


def sort_by_created(items):
    """Default list ordering: created_at ascending (PRD §2.3).

    _created_seq is a monotonic creation counter assigned at insert time so that
    records minted within the same millisecond keep a stable, deterministic order.
    """
    return sorted(items, key=lambda r: r.get("_created_seq", 0))


# --------------------------------------------------------------------------
# Common fields bookkeeping (PRD §2.4)
# --------------------------------------------------------------------------
_seq_counter = {"n": 0}


def _next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_record(with_version=True):
    """Create a record dict with common system fields.

    Full quartet: id, created_at, updated_at, version (begins at 1).
    Payment is leaner (with_version=False): only id + created_at.
    """
    now = store.now()
    rec = {
        "id": store.new_id(),
        "_created_at": now,
        "_created_seq": _next_seq(),
    }
    if with_version:
        rec["_updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation bookkeeping: refresh updated_at, bump version by 1."""
    rec["_updated_at"] = store.now()
    rec["version"] = rec.get("version", 1) + 1


def common_public(rec, with_version=True):
    """Serialize the common system fields into a public dict."""
    out = {
        "id": rec["id"],
        "created_at": iso_z(rec["_created_at"]),
    }
    if with_version:
        out["updated_at"] = iso_z(rec["_updated_at"])
        out["version"] = rec["version"]
    return out
