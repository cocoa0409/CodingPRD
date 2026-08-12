"""Time, decimal, record-mutation and request-validation helpers."""
import math
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, getcontext

from db import clock_now
from errors import ApiError, ERR_INVALID_REQUEST

getcontext().prec = 40


# ---------------------------------------------------------------- time -----

def parse_dt(value):
    """Parse an ISO 8601 instant; normalize to aware UTC. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_dt():
    return clock_now()


def now_str():
    return fmt_dt(clock_now())


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ------------------------------------------------------------- decimals ----

def dec(value):
    """Decimal from JSON number (int/float) without float artifacts."""
    if isinstance(value, bool):
        raise ValueError("bool is not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    raise ValueError("not a number")


def rhu(value):
    """Round half up to whole integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimal places."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def hours_between(start, end):
    """(end - start) in hours as an exact Decimal."""
    secs = Decimal((end - start).total_seconds())
    return secs / Decimal(3600)


def ceil_weeks(start, end):
    return int(math.ceil((end - start) / timedelta(days=7)))


# ------------------------------------------------------------- records -----

def touch(rec):
    """Version bump + updated_at refresh. Caller guarantees a real change."""
    rec["version"] += 1
    rec["updated_at"] = now_str()


def mutate(rec, **changes):
    """Apply field changes; bump version/updated_at only if something changed."""
    changed = False
    for key, value in changes.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


def assign(rec, **changes):
    """Apply field changes without a version bump (caller touches once)."""
    for key, value in changes.items():
        rec[key] = value


def new_record():
    ts = now_str()
    return {"created_at": ts, "updated_at": ts, "version": 1}


# ------------------------------------------------------ serialization ------

def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def public_view(rec, extra=None):
    """Strip internal bookkeeping keys and convert to JSON-safe values."""
    out = {k: jsonable(v) for k, v in rec.items() if not k.startswith("_")}
    if extra:
        out.update(extra)
    return out


# ------------------------------------------------------ body validation ----

def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_unknown(body, allowed):
    for key in body:
        if key not in allowed:
            raise ApiError(ERR_INVALID_REQUEST, 400, "unknown field: %s" % key)


def _check_kind(name, value, kind, enum=None):
    if kind == "str":
        if not isinstance(value, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be a string" % name)
        return value
    if kind == "int":
        if not _is_int(value):
            raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be an integer" % name)
        return value
    if kind == "num":
        if not _is_num(value):
            raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be a number" % name)
        return dec(value)
    if kind == "dt":
        try:
            return parse_dt(value)
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be an ISO8601 datetime" % name)
    if kind == "enum":
        if not isinstance(value, str) or value not in enum:
            raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be one of %s" % (name, sorted(enum)))
        return value
    if kind == "list_str":
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be an array of strings" % name)
        return list(value)
    raise AssertionError("unknown kind %s" % kind)


def req(body, name, kind, enum=None, lo=None, hi=None, gt=None):
    if name not in body or body[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: %s" % name)
    value = _check_kind(name, body[name], kind, enum)
    _check_range(name, value, lo, hi, gt)
    return value


def opt(body, name, kind, enum=None, lo=None, hi=None, gt=None):
    """Optional field; explicit null is treated as absent."""
    if name not in body or body[name] is None:
        return None
    value = _check_kind(name, body[name], kind, enum)
    _check_range(name, value, lo, hi, gt)
    return value


def present(body, name):
    return name in body and body[name] is not None


def raw(body, name):
    return body.get(name)


def _check_range(name, value, lo, hi, gt):
    if lo is not None and value < lo:
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be >= %s" % (name, lo))
    if hi is not None and value > hi:
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be <= %s" % (name, hi))
    if gt is not None and value <= gt:
        raise ApiError(ERR_INVALID_REQUEST, 400, "field %s must be > %s" % (name, gt))
