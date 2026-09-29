"""Foundation: decimal helpers, JSON emission, response envelope, ordered check
pipeline, the logical clock and the in-memory store.

Storage is in-memory only: plain dicts keyed by id, wiped on every process
start.  Nothing is seeded at import time.
"""
import json
import random
import re
import string
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import Response, request

from errors import ApiError, fail

# --------------------------------------------------------------------------
# Decimal arithmetic.  Money is integer cents; every other quantity carries a
# declared decimal precision and is rounded half-up at that precision.
# --------------------------------------------------------------------------
ZERO = Decimal(0)


def q(value, places):
    """Round half-up to `places` decimals, returning a Decimal fixed at that
    exponent so trailing zeros survive serialisation."""
    if value is None:
        return None
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def q1(v):
    return q(v, 1)


def q2(v):
    return q(v, 2)


def q3(v):
    return q(v, 3)


def q4(v):
    return q(v, 4)


def cents(value):
    """Round half-up to a whole cent (integer)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_int(value):
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def dsqrt(value, places):
    """Square root of a Decimal, rounded half-up to `places`."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    if value <= 0:
        return q(ZERO, places)
    return q(value.sqrt(), places)


def dec_places(value):
    exp = value.as_tuple().exponent
    return -exp if exp < 0 else 0


# --------------------------------------------------------------------------
# JSON emission.  A hand-rolled writer so that Decimal values keep their
# declared trailing zeros (0.0000 rather than 0.0).
# --------------------------------------------------------------------------
def _write(o, buf):
    if o is None:
        buf.append("null")
    elif o is True:
        buf.append("true")
    elif o is False:
        buf.append("false")
    elif isinstance(o, Decimal):
        buf.append(format(o, "f"))
    elif isinstance(o, int):
        buf.append(str(o))
    elif isinstance(o, float):
        buf.append(repr(o))
    elif isinstance(o, str):
        buf.append(json.dumps(o))
    elif isinstance(o, (list, tuple)):
        buf.append("[")
        for i, item in enumerate(o):
            if i:
                buf.append(",")
            _write(item, buf)
        buf.append("]")
    elif isinstance(o, dict):
        buf.append("{")
        first = True
        for k, v in o.items():
            if not first:
                buf.append(",")
            first = False
            buf.append(json.dumps(str(k)))
            buf.append(":")
            _write(v, buf)
        buf.append("}")
    elif isinstance(o, datetime):
        buf.append(json.dumps(iso(o)))
    else:
        buf.append(json.dumps(str(o)))
    return buf


def dumps(obj):
    return "".join(_write(obj, []))


# --------------------------------------------------------------------------
# Timestamps.  ISO 8601 UTC with exactly three fractional digits.
# --------------------------------------------------------------------------
TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def iso(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value):
    """Parse an ISO 8601 UTC instant; returns a naive UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = TS_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ".0"
    tz = m.group(8)
    try:
        dt = datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            int(round(float(frac) * 1000000)) % 1000000,
        )
    except ValueError:
        return None
    if tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        off = timedelta(hours=int(tz[1:3]), minutes=int(tz[4:6])) * sign
        dt = dt - off
    return dt


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


def date_str(d):
    return None if d is None else d.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# The store.  Recreated from scratch on every process start.
# --------------------------------------------------------------------------
COLLECTIONS = (
    "product_models", "molds", "oven_stations", "cooling_bays", "technicians",
    "customers", "warehouses", "demand_buckets", "resin_lots", "resin_charges",
    "production_orders", "molding_cycles", "finished_units", "shipments",
    "shipment_lines", "warranty_claims",
)

PREFIX = {
    "product_models": "pmd", "molds": "mld", "oven_stations": "ovs",
    "cooling_bays": "cbay", "technicians": "tec", "customers": "cus",
    "warehouses": "whs", "demand_buckets": "dfb", "resin_lots": "rlot",
    "resin_charges": "rchg", "production_orders": "pord",
    "molding_cycles": "mcyc", "finished_units": "funi", "shipments": "shp",
    "shipment_lines": "sln", "warranty_claims": "wcl",
}

DEFAULT_UTC = datetime(2026, 8, 1, 0, 0, 0)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_UTC
        self.seq = 0
        self.sweep = {
            "expired_resin_lot_count": 0,
            "released_resin_charge_count": 0,
            "aborted_molding_cycle_count": 0,
            "blocked_production_order_count": 0,
        }

    def coll(self, name):
        return getattr(self, name)

    def next_id(self, name):
        self.seq += 1
        token = "".join(random.choice("0123456789abcdef") for _ in range(8))
        return "%s_%09d%s" % (PREFIX[name], self.seq, token)


S = Store()


def now():
    return S.clock


def now_iso():
    return iso(S.clock)


def clock_date():
    return S.clock.date()


def insert(name, row):
    row["id"] = S.next_id(name)
    row["created_at"] = S.clock
    row["updated_at"] = S.clock
    row["version"] = 1
    S.coll(name)[row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = S.clock
    row["version"] = row["version"] + 1
    return row


def rows(name):
    return list(S.coll(name).values())


def sorted_rows(items):
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


# --------------------------------------------------------------------------
# Response envelope.
# --------------------------------------------------------------------------
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def respond(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return Response(dumps(body), status=status, mimetype="application/json")


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return Response(dumps(body), status=status, mimetype="application/json")


# --------------------------------------------------------------------------
# The single ordered check pipeline.  Every endpoint registers its applicable
# checks with the priority the PRD's validation ladder gives them; the pipeline
# evaluates them in ascending priority and the first failure wins.
# --------------------------------------------------------------------------
class Checks(object):
    def __init__(self):
        self._items = []

    def add(self, priority, fn):
        self._items.append((priority, len(self._items), fn))
        return self

    def run(self):
        for _p, _i, fn in sorted(self._items, key=lambda t: (t[0], t[1])):
            fn()


# --------------------------------------------------------------------------
# Pagination (limit/offset per PRD 2.3).
# --------------------------------------------------------------------------
def paginate(items):
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if not re.match(r"^-?\d+$", raw or ""):
            fail("ERR_VALIDATION", "limit must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        if not re.match(r"^-?\d+$", raw or ""):
            fail("ERR_VALIDATION", "offset must be an integer.")
        offset = int(raw)
        if offset < 0:
            fail("ERR_VALIDATION", "offset must not be negative.")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
