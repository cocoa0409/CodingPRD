"""Request-schema validation (PRD §2.7 precedence step 4 -> ERR_VALIDATION)."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import fail

_MISSING = object()


def bad(msg):
    fail("ERR_VALIDATION", msg)


def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object")
    return payload


def _present(data, key, required):
    if key not in data or data[key] is None:
        if required:
            bad("Missing required field: %s" % key)
        return False
    return True


def string(data, key, required=True, min_len=None, max_len=None, default=None):
    if not _present(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("Field %s must be a string" % key)
    if min_len is not None and len(value) < min_len:
        bad("Field %s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field %s must be at most %d characters" % (key, max_len))
    return value


def enum(data, key, allowed, required=True, default=None):
    if not _present(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field %s must be one of %s" % (key, ", ".join(allowed)))
    return value


def boolean(data, key, required=False, default=None):
    if not _present(data, key, required):
        return default
    value = data[key]
    if not isinstance(value, bool):
        bad("Field %s must be a boolean" % key)
    return value


def integer(data, key, required=True, minimum=None, maximum=None, default=None):
    if not _present(data, key, required):
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            bad("Field %s must be an integer" % key)
    if minimum is not None and value < minimum:
        bad("Field %s must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field %s must be <= %s" % (key, maximum))
    return value


def number(data, key, required=True, minimum=None, maximum=None, default=None,
           exclusive_min=None):
    """A pounds/hours quantity carried as Decimal."""
    if not _present(data, key, required):
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("Field %s must be a number" % key)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("Field %s must be a number" % key)
    if not dec.is_finite():
        bad("Field %s must be a finite number" % key)
    if exclusive_min is not None and dec <= store.D(exclusive_min):
        bad("Field %s must be > %s" % (key, exclusive_min))
    if minimum is not None and dec < store.D(minimum):
        bad("Field %s must be >= %s" % (key, minimum))
    if maximum is not None and dec > store.D(maximum):
        bad("Field %s must be <= %s" % (key, maximum))
    return dec


def parse_instant(raw, key):
    if not isinstance(raw, str) or not raw.strip():
        bad("Field %s must be an ISO 8601 timestamp" % key)
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            bad("Field %s must be an ISO 8601 timestamp" % key)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def instant(data, key, required=True, default=None):
    if not _present(data, key, required):
        return default
    return parse_instant(data[key], key)


def date(data, key, required=True, default=None):
    """A UTC date at midnight (PRD §2.4)."""
    if not _present(data, key, required):
        return default
    return store.day_of(parse_instant(data[key], key))


# ----------------------------------------------------------- query args ----
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        if limit_raw.strip() == "":
            bad("limit must be an integer")
        try:
            limit = int(limit_raw)
        except ValueError:
            bad("limit must be an integer")
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100")
    if offset_raw is not None:
        if offset_raw.strip() == "":
            bad("offset must be an integer")
        try:
            offset = int(offset_raw)
        except ValueError:
            bad("offset must be an integer")
        if offset < 0:
            bad("offset must be >= 0")
    return limit, offset


def q_enum(key, allowed):
    value = request.args.get(key)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter %s must be one of %s" % (key, ", ".join(allowed)))
    return value


def q_str(key):
    value = request.args.get(key)
    if value is None:
        return None
    return value


def q_date(key):
    value = request.args.get(key)
    if value is None:
        return None
    return store.day_of(parse_instant(value, key))


def page(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return [serializer(r) for r in window], total
