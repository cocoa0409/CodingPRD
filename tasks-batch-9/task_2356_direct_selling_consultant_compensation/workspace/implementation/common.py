"""Shared primitives: rounding, timestamps, shape validation, pagination."""

import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import request

from db import db, new_id, next_seq, wall_now
from errors import ApiError

_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d{1,9})?[Zz]$")


# --------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------

def rhu(numerator, denominator):
    """Exact rational numerator/denominator rounded half up (away from zero).

    Implemented on exact integers so no binary floating point is ever involved;
    equivalent to Decimal(n)/Decimal(d) quantized with ROUND_HALF_UP at
    unlimited precision.
    """
    numerator = int(numerator)
    denominator = int(denominator)
    if denominator == 0:
        raise ZeroDivisionError("rhu denominator is zero")
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))


def apply_bp(amount, rate_bp):
    """amount * rate_bp / 10000, rounded half up on this single multiplication."""
    return rhu(int(amount) * int(rate_bp), 10000)


def trunc_div(numerator, denominator):
    """Truncate toward zero (the sell-through exception, PRD section 2.6)."""
    numerator = int(numerator)
    denominator = int(denominator)
    quotient = abs(numerator) // abs(denominator)
    if (numerator < 0) != (denominator < 0):
        return -quotient
    return quotient


# --------------------------------------------------------------------------
# Timestamps and the logical clock
# --------------------------------------------------------------------------

def is_iso_z(value):
    return isinstance(value, str) and bool(_DT_RE.match(value))


def parse_dt(value):
    if not is_iso_z(value):
        return None
    text = value[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000000")[:6]
        text = head + "." + frac
    try:
        dt = datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f" if "." in text else "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)


def fmt_dt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (
        dt.microsecond // 1000
    )


def clock_str():
    return db.clock


def clock_dt():
    return parse_dt(db.clock)


def plus_days(dt, days):
    return dt + timedelta(days=int(days))


# --------------------------------------------------------------------------
# Row bookkeeping
# --------------------------------------------------------------------------

def new_row(with_version=True):
    row = {"id": new_id(), "created_at": wall_now()}
    if with_version:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    if "version" in row:
        row["updated_at"] = wall_now()
        row["version"] = int(row["version"]) + 1
    return row


# --------------------------------------------------------------------------
# Request body / shape validation  (all failures -> ERR_VALIDATION)
# --------------------------------------------------------------------------

def bad():
    raise ApiError("ERR_VALIDATION")


def raw_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        bad()
    return body


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_field(body, name):
    if name not in body or body[name] is None:
        bad()
    return body[name]


def req_str(body, name, min_len=1, max_len=None):
    value = req_field(body, name)
    if not isinstance(value, str):
        bad()
    if len(value) < min_len:
        bad()
    if max_len is not None and len(value) > max_len:
        bad()
    return value


def opt_str(body, name, default=None, min_len=1, max_len=None):
    if name not in body or body[name] is None:
        return default
    return req_str(body, name, min_len=min_len, max_len=max_len)


def req_int(body, name, minimum=None, maximum=None):
    value = req_field(body, name)
    if not is_int(value):
        bad()
    if minimum is not None and value < minimum:
        bad()
    if maximum is not None and value > maximum:
        bad()
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_bool(body, name):
    value = req_field(body, name)
    if not isinstance(value, bool):
        bad()
    return value


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_bool(body, name)


def req_enum(body, name, members):
    value = req_str(body, name)
    if value not in members:
        bad()
    return value


def opt_enum(body, name, members, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, members)


def req_dt_str(body, name):
    value = req_field(body, name)
    if not is_iso_z(value) or parse_dt(value) is None:
        bad()
    return value


def opt_dt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return req_dt_str(body, name)


def req_list(body, name, min_len=1, max_len=None):
    value = req_field(body, name)
    if not isinstance(value, list):
        bad()
    if len(value) < min_len:
        bad()
    if max_len is not None and len(value) > max_len:
        bad()
    for element in value:
        if not isinstance(element, dict):
            bad()
    return value


# --------------------------------------------------------------------------
# Pagination and list filters
# --------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def pagination():
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        if not re.match(r"^-?\d+$", raw_limit.strip() or "x"):
            bad()
        limit = int(raw_limit)
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            bad()
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        if not re.match(r"^-?\d+$", raw_offset.strip() or "x"):
            bad()
        offset = int(raw_offset)
        if offset < OFFSET_MIN:
            bad()
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def q_enum(name, members):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        bad()
    return value


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    bad()


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset: offset + limit], total
