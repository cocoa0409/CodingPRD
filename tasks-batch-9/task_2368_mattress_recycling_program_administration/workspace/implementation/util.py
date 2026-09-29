"""Shared helpers: timestamps, rounding discipline, body validation, records."""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR

from flask import g, request

from db import clock, db, new_id
from errors import ApiError

# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------


def iso_ms(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """Wall-clock ISO 8601 UTC with exactly three fractional digits."""
    return iso_ms(datetime.now(timezone.utc))


def iso_clock(dt):
    """Render a logical-clock instant the same way the clock itself reports it.

    The clock echoes the instant it was set to, so an instant that lands on a
    whole second carries no fractional part; only a sub-second instant needs the
    three fractional digits.  Derived clock instants (a quarantine expiry, for
    instance) must render identically to the stamps taken straight off the clock.
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso_ms(dt)


def parse_dt(value):
    """Parse an ISO 8601 instant; raises ValueError when unparseable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def try_parse_dt(value):
    try:
        return parse_dt(value)
    except Exception:
        return None


def plus_days(dt, days):
    return dt + timedelta(days=days)


# --------------------------------------------------------------------------
# Rounding discipline (PRD §2.6)
# --------------------------------------------------------------------------


def dec(value):
    return Decimal(str(value))


def rhu(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def two_dp(value):
    """Round half up to two decimals and return a JSON number."""
    return float(rhu(value, 2))


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------


def record_stamp():
    """The instant written into created_at / updated_at.

    PRD §2.4: the server never falls back to real time — every read of the
    current instant goes through the logical clock — and created_at / updated_at
    are ISO 8601 UTC with three fractional digits.
    """
    return iso_ms(clock.now())


def base_record(with_version=True):
    stamp = record_stamp()
    rec = {"id": new_id(), "created_at": stamp}
    if with_version:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and bump version at most once per HTTP request."""
    if "version" not in rec:
        return rec
    rec["updated_at"] = record_stamp()
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if rec["id"] not in touched:
        touched.add(rec["id"])
        rec["version"] = rec["version"] + 1
    return rec


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_records(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# Request body validation (PRD §2.10 step 3)
# --------------------------------------------------------------------------


class F(object):
    def __init__(self, name, kind, required=True, enum=None, minimum=None,
                 maximum=None, pattern=None, nullable=False, exclusive_min=None,
                 min_items=None, item_enum=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.pattern = pattern
        self.nullable = nullable
        self.exclusive_min = exclusive_min
        self.min_items = min_items
        self.item_enum = item_enum


def _bad(field):
    raise ApiError("ERR_INVALID_REQUEST",
                   "Invalid or missing field: %s." % field)


def raw_body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def validate_body(specs):
    payload = raw_body()
    out = {}
    for spec in specs:
        name = spec.name
        if name not in payload:
            if spec.required:
                _bad(name)
            continue
        value = payload[name]
        if value is None:
            if spec.nullable:
                out[name] = None
                continue
            _bad(name)
        kind = spec.kind
        if kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                _bad(name)
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _bad(name)
        elif kind == "string":
            if not isinstance(value, str):
                _bad(name)
        elif kind == "bool":
            if not isinstance(value, bool):
                _bad(name)
        elif kind == "enum":
            if not isinstance(value, str) or value not in spec.enum:
                _bad(name)
        elif kind == "datetime":
            if not isinstance(value, str) or try_parse_dt(value) is None:
                _bad(name)
        elif kind == "array":
            if not isinstance(value, list):
                _bad(name)
            if spec.min_items is not None and len(value) < spec.min_items:
                _bad(name)
            for item in value:
                if not isinstance(item, str) or isinstance(item, bool):
                    _bad(name)
                if spec.item_enum is not None and item not in spec.item_enum:
                    _bad(name)
        if spec.pattern is not None and not re.match(spec.pattern, value or ""):
            _bad(name)
        if spec.minimum is not None and value < spec.minimum:
            _bad(name)
        if spec.maximum is not None and value > spec.maximum:
            _bad(name)
        if spec.exclusive_min is not None and not value > spec.exclusive_min:
            _bad(name)
        out[name] = value
    return out


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------


def pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0.")
    return limit, offset


def apply_filters(records, filters):
    """filters: list of (query_param_name, record_field_name)."""
    args = request.args
    out = records
    for param, field in filters:
        value = args.get(param)
        if value is None or value == "":
            continue
        out = [r for r in out if str(r.get(field)) == value]
    return out


def paginate(records, limit, offset):
    total = len(records)
    window = records[offset:offset + limit]
    return window, total
