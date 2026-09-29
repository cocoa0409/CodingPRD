"""Request-body schema validation -- PRD section 2.11 rule 4 (ERR_INVALID_REQUEST).

Every required field present, no unknown fields, correct types, legal enum
members, each number inside its declared bounds.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from core import UTC, dec, fail, parse_dt, q2, q4

_MISSING = object()


class F(object):
    def __init__(self, name, kind, required=True, default=_MISSING, enum=None,
                 gt=None, gte=None, lte=None, lt=None, min_len=None,
                 max_len=None, exact_len=None, month_boundary=False,
                 element=None, non_blank=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.gt = gt
        self.gte = gte
        self.lte = lte
        self.lt = lt
        self.min_len = min_len
        self.max_len = max_len
        self.exact_len = exact_len
        self.month_boundary = month_boundary
        self.element = element
        self.non_blank = non_blank


def read_json():
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Malformed JSON body")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return payload


def parse_body(specs):
    payload = read_json()
    known = set(spec.name for spec in specs)
    for key in payload.keys():
        if key not in known:
            fail("ERR_INVALID_REQUEST", "Unknown field '%s'" % key)
    out = {}
    for spec in specs:
        if spec.name not in payload:
            if spec.required:
                fail("ERR_INVALID_REQUEST", "Missing required field '%s'" % spec.name)
            out[spec.name] = None if spec.default is _MISSING else spec.default
            continue
        out[spec.name] = _coerce(spec, payload[spec.name])
    out["_present"] = set(payload.keys())
    return out


def _bad(spec, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s" % (spec.name, detail))


def _coerce(spec, value):
    kind = spec.kind
    if kind == "string":
        if not isinstance(value, str):
            _bad(spec, "must be a string")
        if spec.non_blank and value.strip() == "":
            _bad(spec, "must not be blank")
        if spec.exact_len is not None and len(value) != spec.exact_len:
            _bad(spec, "must be exactly %d characters" % spec.exact_len)
        if spec.min_len is not None and len(value) < spec.min_len:
            _bad(spec, "must be at least %d characters" % spec.min_len)
        if spec.max_len is not None and len(value) > spec.max_len:
            _bad(spec, "must be at most %d characters" % spec.max_len)
        return value
    if kind == "enum":
        if not isinstance(value, str):
            _bad(spec, "must be a string")
        if value not in spec.enum:
            _bad(spec, "must be one of %s" % ", ".join(spec.enum))
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad(spec, "must be a boolean")
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(spec, "must be an integer")
        _bounds(spec, Decimal(value))
        return value
    if kind in ("money", "pct"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(spec, "must be a number")
        try:
            raw = dec(value)
        except (InvalidOperation, ValueError):
            _bad(spec, "must be a number")
        if not raw.is_finite():
            _bad(spec, "must be a finite number")
        rounded = q2(raw) if kind == "money" else q4(raw)
        _bounds(spec, rounded)
        return rounded
    if kind == "datetime":
        parsed = parse_dt(value)
        if spec.month_boundary:
            if (parsed.day != 1 or parsed.hour != 0 or parsed.minute != 0
                    or parsed.second != 0 or parsed.microsecond != 0):
                _bad(spec, "must be the first instant of a calendar month")
        return parsed
    if kind == "string_array":
        if not isinstance(value, list):
            _bad(spec, "must be an array")
        for item in value:
            if not isinstance(item, str):
                _bad(spec, "must contain only strings")
        return list(value)
    if kind == "schedule":
        return _schedule(spec, value)
    raise AssertionError("unknown field kind " + kind)


def _bounds(spec, value):
    if spec.gt is not None and not value > dec(spec.gt):
        _bad(spec, "must be greater than %s" % spec.gt)
    if spec.gte is not None and not value >= dec(spec.gte):
        _bad(spec, "must be greater than or equal to %s" % spec.gte)
    if spec.lt is not None and not value < dec(spec.lt):
        _bad(spec, "must be less than %s" % spec.lt)
    if spec.lte is not None and not value <= dec(spec.lte):
        _bad(spec, "must be less than or equal to %s" % spec.lte)


def _schedule(spec, value):
    if not isinstance(value, list):
        _bad(spec, "must be an array")
    buckets = []
    for item in value:
        if not isinstance(item, dict):
            _bad(spec, "must contain objects")
        for key in item.keys():
            if key not in ("month_index", "planned_amount"):
                fail("ERR_INVALID_REQUEST",
                     "Unknown field '%s' inside spend_schedule" % key)
        if "month_index" not in item or "planned_amount" not in item:
            fail("ERR_INVALID_REQUEST",
                 "Each spend_schedule bucket requires month_index and planned_amount")
        month_index = item["month_index"]
        planned = item["planned_amount"]
        if isinstance(month_index, bool) or not isinstance(month_index, int):
            fail("ERR_INVALID_REQUEST", "spend_schedule.month_index must be an integer")
        if month_index < 1 or month_index > 31:
            fail("ERR_INVALID_REQUEST", "spend_schedule.month_index must be in 1..31")
        if isinstance(planned, bool) or not isinstance(planned, (int, float)):
            fail("ERR_INVALID_REQUEST", "spend_schedule.planned_amount must be a number")
        amount = q2(dec(planned))
        if amount < Decimal("0.00"):
            fail("ERR_INVALID_REQUEST",
                 "spend_schedule.planned_amount must be greater than or equal to 0.00")
        buckets.append({"month_index": month_index, "planned_amount": amount})
    return buckets
