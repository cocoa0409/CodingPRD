"""Shared helpers: common fields, pagination, numeric parsing."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import db, new_id, now_iso
from errors import err, ERR_VALIDATION


def init_common(record):
    """Set common system fields: id, created_at, updated_at, version, _seq."""
    record["id"] = new_id()
    ts = now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Bump version + updated_at on mutation."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()


def public(record, drop=("_seq",)):
    """Return a copy without internal fields."""
    return {k: v for k, v in record.items() if k not in drop}


def round2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round3(value):
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


# ---------------- pagination ----------------

def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items):
    """Sort by created_at asc (stable via _seq), then page."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    has_more = (offset + len(page)) < total
    return [public(r) for r in page], limit, offset, total, has_more


# ---------------- body parsing ----------------

def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_VALIDATION, f"Missing required field: {f}")


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(ERR_VALIDATION, f"{field} must be a number")
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_VALIDATION, f"{field} must be an integer")
    return value


def as_str(value, field):
    if not isinstance(value, str):
        raise err(ERR_VALIDATION, f"{field} must be a string")
    return value
