"""Request-shape validation (rung 4), pagination (rung 5), parsing and rounding."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError

# --------------------------------------------------------------------------- #
# rounding discipline (PRD 2.7)
# --------------------------------------------------------------------------- #


def dec(value):
    """Exact Decimal from an int / float / Decimal without binary artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def money(value):
    """Round half up to a whole cent and return a Python int."""
    return int(round_half_up(value, 0))


def num(value, places):
    """Round half up to `places` decimals and return a JSON number."""
    return float(round_half_up(value, places))


# --------------------------------------------------------------------------- #
# datetime handling
# --------------------------------------------------------------------------- #


def parse_datetime(raw):
    if not isinstance(raw, str) or raw.strip() == "":
        raise ValueError("not a datetime")
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("not a datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(value):
    if value is None:
        return None
    dt = value.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_days(value, days):
    return value + timedelta(days=days)


def whole_days_between(start, end):
    """Elapsed whole days, truncated downward (PRD 2.7)."""
    delta = end - start
    return delta.days if delta.total_seconds() >= 0 else -((-delta).days)


def minus_months(value, months):
    """Shift an instant back by whole months (used for the 24-month recency test)."""
    year = value.year
    month = value.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = value.day
    while True:
        try:
            return value.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


# --------------------------------------------------------------------------- #
# field specifications
# --------------------------------------------------------------------------- #


class Field:
    def __init__(
        self,
        name,
        kind,
        required=False,
        enum=None,
        minimum=None,
        maximum=None,
        exclusive_min=None,
        exclusive_max=None,
        nullable=False,
        nonempty=True,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_min = exclusive_min
        self.exclusive_max = exclusive_max
        self.nullable = nullable
        self.nonempty = nonempty


def _bad():
    raise ApiError("ERR_VALIDATION")


def _coerce(field, value):
    kind = field.kind
    if kind == "string":
        if not isinstance(value, str):
            _bad()
        if field.nonempty and value.strip() == "":
            _bad()
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in field.enum:
            _bad()
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad()
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad()
        _check_range(field, Decimal(value))
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad()
        _check_range(field, dec(value))
        return value
    if kind == "datetime":
        try:
            return parse_datetime(value)
        except ValueError:
            _bad()
    _bad()


def _check_range(field, value):
    if field.minimum is not None and value < dec(field.minimum):
        _bad()
    if field.maximum is not None and value > dec(field.maximum):
        _bad()
    if field.exclusive_min is not None and value <= dec(field.exclusive_min):
        _bad()
    if field.exclusive_max is not None and value >= dec(field.exclusive_max):
        _bad()


def parse_body(fields):
    """Rung 4.  Rejects unknown / system-managed / computed fields outright."""
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        _bad()

    allowed = {f.name for f in fields}
    for key in raw:
        if key not in allowed:
            _bad()

    parsed = {}
    for field in fields:
        if field.name not in raw:
            if field.required:
                _bad()
            continue
        value = raw[field.name]
        if value is None:
            if field.required or not field.nullable:
                _bad()
            parsed[field.name] = None
            continue
        parsed[field.name] = _coerce(field, value)
    return parsed


# --------------------------------------------------------------------------- #
# pagination and list filters
# --------------------------------------------------------------------------- #


def pagination():
    """Rung 5.  Defaults limit 10 / offset 0, limit in [1, 100], offset >= 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")

    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


_MISSING = object()


def filter_rows(rows, specs):
    """specs: list of (query_param, row_field, kind)."""
    out = rows
    for param, field_name, kind in specs:
        raw = request.args.get(param)
        if raw is None:
            continue
        if kind == "integer":
            try:
                wanted = int(raw)
            except (TypeError, ValueError):
                return []
        else:
            wanted = raw
        out = [r for r in out if r.get(field_name, _MISSING) == wanted]
    return out


def paginate(rows, limit, offset):
    return rows[offset: offset + limit]
