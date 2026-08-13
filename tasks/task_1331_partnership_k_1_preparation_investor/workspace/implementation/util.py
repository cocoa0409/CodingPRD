"""Shared utilities: errors, envelope, parsing, rounding."""
import random
import re
import string
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction

from flask import jsonify

from db import fmt_ts, now


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        raise ValueError("invalid date")
    return date.fromisoformat(s)


def parse_datetime(s):
    if not isinstance(s, str):
        raise ValueError("invalid datetime")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def rhu(value):
    """Round half-up (ties away from zero) to integer cents. Accepts int/Fraction/Decimal."""
    if isinstance(value, int):
        return value
    if isinstance(value, Fraction):
        with localcontext() as ctx:
            ctx.prec = 60
            d = Decimal(value.numerator) / Decimal(value.denominator)
            return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    with localcontext() as ctx:
        ctx.prec = 60
        return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def envelope(data, code=200, pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def error_envelope(err):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": fmt_ts(now()),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def paginate(items):
    """Apply limit/offset pagination. items must already be sorted."""
    from flask import request

    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
