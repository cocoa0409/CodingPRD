"""Shared helpers: datetime parsing/formatting, decimal math, field validation."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import raise_err, ERR_INVALID_REQUEST

_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_dt(value):
    """Parse an ISO-8601 datetime (or bare date, treated as midnight UTC)."""
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "Expected ISO-8601 datetime string, got %r" % (value,))
    s = value.strip()
    try:
        if _DATE_ONLY.fullmatch(s):
            s = s + "T00:00:00Z"
        s2 = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
        dt = datetime.fromisoformat(s2)
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "Malformed datetime: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (d.microsecond // 1000))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def to_jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    return value


def pub(entity):
    """Public view of an entity: strip internal keys, convert Decimal/datetime."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        out[k] = to_jsonable(v)
    return out


def new_base():
    t = db.now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    entity["updated_at"] = db.now()
    entity["version"] = int(entity.get("version", 1)) + 1


# ---------------------------------------------------------------------------
# Request-body field validators (request shape step -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def _bad(field, why):
    raise_err(ERR_INVALID_REQUEST, "Field '%s' %s" % (field, why))


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        _bad(field, "is required and must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_int(body, field, minv=None, maxv=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "is required and must be an integer")
    if minv is not None and v < minv:
        _bad(field, "must be >= %s" % minv)
    if maxv is not None and v > maxv:
        _bad(field, "must be <= %s" % maxv)
    return v


def opt_int(body, field, default=None, minv=None, maxv=None):
    v = body.get(field)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "must be an integer")
    if minv is not None and v < minv:
        _bad(field, "must be >= %s" % minv)
    if maxv is not None and v > maxv:
        _bad(field, "must be <= %s" % maxv)
    return v


def req_num(body, field, minv=None, max_dp=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        _bad(field, "is required and must be a number")
    d = v if isinstance(v, Decimal) else Decimal(v)
    if minv is not None and d < Decimal(str(minv)):
        _bad(field, "must be >= %s" % minv)
    if max_dp is not None:
        q = Decimal(1).scaleb(-max_dp)
        try:
            if d != d.quantize(q):
                _bad(field, "allows at most %d decimal places" % max_dp)
        except Exception:
            _bad(field, "is not a valid number")
    return d


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        _bad(field, "is required and must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, "must be one of %s" % (", ".join(sorted(allowed))))
    return v


def req_dt(body, field):
    v = body.get(field)
    if v is None:
        _bad(field, "is required and must be an ISO-8601 datetime")
    return parse_dt(v)
