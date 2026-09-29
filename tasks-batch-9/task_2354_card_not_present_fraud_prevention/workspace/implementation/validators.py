"""Request-shape validation helpers (validation priorities 14-20).

Every failure in this module is ERR_VALIDATION (422) per the scaffold.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal

from flask import request

from db import db
from errors import ApiError

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_BIN_RE = re.compile(r"^[0-9]{6}$")


def bad():
    raise ApiError("ERR_VALIDATION")


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad()
    return data


def present(payload, name):
    return name in payload and payload[name] is not None


def require_present(payload, *names):
    for name in names:
        if not present(payload, name):
            bad()


def as_str(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad()
    return value


def as_bool(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad()
    return value


def as_int(payload, name, required=True, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad()
    if minimum is not None and value < minimum:
        bad()
    if maximum is not None and value > maximum:
        bad()
    return value


def as_decimal(payload, name, required=True, default=None, minimum=None, maximum=None,
               exclusive_minimum=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad()
    dec = Decimal(str(value))
    if minimum is not None and dec < Decimal(str(minimum)):
        bad()
    if maximum is not None and dec > Decimal(str(maximum)):
        bad()
    if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
        bad()
    return dec


def as_enum(payload, name, allowed, required=True, default=None):
    value = as_str(payload, name, required=required, default=None)
    if value is None:
        return default
    if value not in allowed:
        bad()
    return value


def as_country(payload, name, required=True, default=None):
    value = as_str(payload, name, required=required, default=default)
    if value is None:
        return default
    if not _COUNTRY_RE.match(value):
        bad()
    return value


def as_card_bin(payload, name):
    value = as_str(payload, name)
    if not _BIN_RE.match(value):
        bad()
    return value


def as_string_array(payload, name, allowed, required=True):
    if not present(payload, name):
        if required:
            bad()
        return None
    value = payload[name]
    if not isinstance(value, list):
        bad()
    if len(value) == 0:
        bad()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad()
    return list(value)


def parse_dt(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def as_datetime(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            bad()
        return default
    parsed = parse_dt(payload[name])
    if parsed is None:
        bad()
    return parsed


# -------------------------------------------------------------------- queries
def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad()
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad()
    if limit < 1 or limit > 100:
        bad()
    if offset < 0:
        bad()
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad()
    return value


def query_str(name):
    return request.args.get(name)


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad()


def apply_filters(rows, filters):
    """filters: list of (field_name, expected_value); None values are skipped."""
    result = rows
    for field, expected in filters:
        if expected is None:
            continue
        result = [r for r in result if r.get(field) == expected]
    return result


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def lookup(collection, key, error_id):
    if not isinstance(key, str):
        raise ApiError(error_id)
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def optional_fk(payload, name, collection, error_id):
    """Body FK resolution (priority 11): absent/null is deferred to shape checks."""
    if not present(payload, name):
        return None
    return lookup(collection, payload[name], error_id)


def required_fk(payload, name, collection, error_id):
    if not present(payload, name):
        return None
    return lookup(collection, payload[name], error_id)


def clock_now():
    return db.now()
