import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import raise_err


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def rhu(numerator, denominator=1):
    """Round-half-up integer division in exact arithmetic (Decimal ROUND_HALF_UP)."""
    return int(
        (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def parse_body(required=False):
    """Parse the JSON request body; malformed JSON is an ERR_INVALID_REQUEST."""
    from flask import request

    if not request.data:
        if required:
            raise_err("ERR_INVALID_REQUEST", "Request body is required")
        return {}
    try:
        body = request.get_json(silent=False)
    except Exception:
        raise_err("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if body is None:
        if required:
            raise_err("ERR_INVALID_REQUEST", "Request body is required")
        return {}
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def req_present(body, field):
    if field not in body or body[field] is None:
        raise_err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return body[field]


def req_str(body, field):
    v = req_present(body, field)
    if not isinstance(v, str) or v == "":
        raise_err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def opt_str_nullable(body, field):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", f"Field {field} must be a string or null")
    return v


def req_int(body, field, minv=None, maxv=None):
    v = req_present(body, field)
    if not is_int(v):
        raise_err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minv is not None and v < minv:
        raise_err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minv}")
    if maxv is not None and v > maxv:
        raise_err("ERR_INVALID_REQUEST", f"Field {field} must be <= {maxv}")
    return v


def opt_int_nullable(body, field, minv=None):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not is_int(v):
        raise_err("ERR_INVALID_REQUEST", f"Field {field} must be an integer or null")
    if minv is not None and v < minv:
        raise_err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minv}")
    return v


def req_enum(body, field, allowed):
    v = req_present(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise_err(
            "ERR_INVALID_REQUEST",
            f"Field {field} must be one of {', '.join(allowed)}",
        )
    return v
