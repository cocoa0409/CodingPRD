"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from flask import jsonify

from db import now_iso

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def display_units(value):
    """Share units are exact rationals stored to four decimal places."""
    if value is None:
        return None
    quantised = (Decimal(Fraction(value).numerator) / Decimal(Fraction(value).denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(quantised)


def serialize(value):
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    if isinstance(value, Fraction):
        return display_units(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(data if data is not None else {}),
    }
    return jsonify(body), status


def ok_list(rows, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(rows)) < total_count,
        }),
        "response_type": "array",
        "data": serialize(list(rows)),
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
