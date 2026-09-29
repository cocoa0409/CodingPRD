"""Request shape validation (PRD 2.7 check 3) and pagination parsing (2.3)."""

from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_dt
from errors import ApiError

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def bad(field=None, detail=None):
    msg = "The request payload or query string is malformed."
    if field:
        msg = "Invalid or missing field '%s'." % field
    if detail:
        msg = detail
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None or not isinstance(parsed, dict):
        bad(detail="Request body must be a JSON object.")
    return parsed


def _present(b, key):
    return key in b and b[key] is not None


def req_str(b, key, min_len=1, max_len=None):
    if not _present(b, key):
        bad(key)
    value = b[key]
    if not isinstance(value, str):
        bad(key)
    if len(value) < min_len:
        bad(key)
    if max_len is not None and len(value) > max_len:
        bad(key)
    return value


def opt_str(b, key, min_len=1, max_len=None, default=None):
    if key not in b or b[key] is None:
        return default
    return req_str(b, key, min_len, max_len)


def req_id(b, key):
    return req_str(b, key, 1, None)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(b, key, minimum=None, maximum=None):
    if not _present(b, key):
        bad(key)
    value = b[key]
    if not _is_int(value):
        bad(key)
    if minimum is not None and value < minimum:
        bad(key)
    if maximum is not None and value > maximum:
        bad(key)
    return value


def opt_int(b, key, minimum=None, maximum=None, default=None):
    if key not in b or b[key] is None:
        return default
    return req_int(b, key, minimum, maximum)


def req_bool(b, key):
    if not _present(b, key):
        bad(key)
    value = b[key]
    if not isinstance(value, bool):
        bad(key)
    return value


def opt_bool(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    return req_bool(b, key)


def req_enum(b, key, allowed):
    value = req_str(b, key, 1, None)
    if value not in allowed:
        bad(key)
    return value


def opt_enum(b, key, allowed, default=None):
    if key not in b or b[key] is None:
        return default
    return req_enum(b, key, allowed)


def req_dt(b, key):
    raw = req_str(b, key, 1, None)
    parsed = parse_dt(raw)
    if parsed is None:
        bad(key)
    return raw, parsed


def opt_dt(b, key):
    if key not in b or b[key] is None:
        return None, None
    return req_dt(b, key)


def req_digits(b, key, count):
    value = req_str(b, key, count, count)
    if not value.isdigit() or len(value) != count:
        bad(key)
    return value


def req_decimal(b, key, minimum=None, maximum=None, places=2):
    if not _present(b, key):
        bad(key)
    value = b[key]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad(key)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad(key)
    if not dec.is_finite():
        bad(key)
    dec = dec.quantize(Decimal("0.01"))
    if minimum is not None and dec < minimum:
        bad(key)
    if maximum is not None and dec > maximum:
        bad(key)
    return dec


def opt_decimal(b, key, minimum=None, maximum=None, default=None):
    if key not in b or b[key] is None:
        return default
    return req_decimal(b, key, minimum, maximum)


def must_be_null(b, key):
    if key in b and b[key] is not None:
        bad(key)


def req_list(b, key, min_len=0):
    if not _present(b, key):
        bad(key)
    value = b[key]
    if not isinstance(value, list):
        bad(key)
    if len(value) < min_len:
        bad(key)
    return value


def pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("limit")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            bad("limit")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("offset")
        if offset < OFFSET_DEFAULT:
            bad("offset")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def filter_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    if value == "":
        return None
    return value
