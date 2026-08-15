"""Request-shape validators (validation ladder step 4 -> ERR_INVALID_REQUEST)."""
import re
from datetime import datetime, timezone

from errors import err, ERR_INVALID_REQUEST

_MISSING = object()


def _bad(msg):
    raise err(ERR_INVALID_REQUEST, msg)


def req_str(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING or not isinstance(v, str) or v == "":
        _bad("missing or invalid field: %s" % field)
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        _bad("invalid field: %s" % field)
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field, _MISSING)
    if v is _MISSING or isinstance(v, bool) or not isinstance(v, int):
        _bad("missing or invalid field: %s" % field)
    if minimum is not None and v < minimum:
        _bad("field out of range: %s" % field)
    if maximum is not None and v > maximum:
        _bad("field out of range: %s" % field)
    return v


def opt_int(body, field, minimum=None, maximum=None):
    if field not in body or body.get(field) is None:
        return None
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("invalid field: %s" % field)
    if minimum is not None and v < minimum:
        _bad("field out of range: %s" % field)
    if maximum is not None and v > maximum:
        _bad("field out of range: %s" % field)
    return v


def req_number(body, field, gt=None, gte=None):
    v = body.get(field, _MISSING)
    if v is _MISSING or isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("missing or invalid field: %s" % field)
    if gt is not None and not (v > gt):
        _bad("field out of range: %s" % field)
    if gte is not None and not (v >= gte):
        _bad("field out of range: %s" % field)
    return v


def opt_number(body, field, gt=None):
    if field not in body or body.get(field) is None:
        return None
    return req_number(body, field, gt=gt)


def req_bool(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING or not isinstance(v, bool):
        _bad("missing or invalid field: %s" % field)
    return v


def req_enum(body, field, values):
    v = body.get(field, _MISSING)
    if v is _MISSING or not isinstance(v, str) or v not in values:
        _bad("missing or invalid field: %s" % field)
    return v


def opt_enum(body, field, values, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, values)


def parse_datetime_value(v, field):
    if not isinstance(v, str):
        _bad("invalid datetime: %s" % field)
    s = v.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        _bad("invalid datetime: %s" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, field):
    v = body.get(field, _MISSING)
    if v is _MISSING:
        _bad("missing field: %s" % field)
    return parse_datetime_value(v, field)


def opt_datetime(body, field):
    if field not in body or body.get(field) is None:
        return None
    return parse_datetime_value(body.get(field), field)


_SY_RE = re.compile(r"^(\d{4})-(\d{4})$")


def parse_school_year(value, field="school_year"):
    """'YYYY-YYYY' naming two consecutive years; returns (y1, y2)."""
    if not isinstance(value, str):
        _bad("invalid field: %s" % field)
    m = _SY_RE.match(value)
    if not m:
        _bad("malformed school_year")
    y1, y2 = int(m.group(1)), int(m.group(2))
    if y2 != y1 + 1:
        _bad("school_year must name consecutive years")
    return y1, y2


def school_year_window(school_year):
    y1, y2 = parse_school_year(school_year)
    start = datetime(y1, 7, 1, tzinfo=timezone.utc)
    end_excl = datetime(y2, 7, 1, tzinfo=timezone.utc)
    return start, end_excl


def sy_contains(school_year, dt):
    start, end_excl = school_year_window(school_year)
    return start <= dt < end_excl


def sy_window_contained(school_year, starts_at, ends_at):
    start, end_excl = school_year_window(school_year)
    return starts_at >= start and ends_at <= end_excl
