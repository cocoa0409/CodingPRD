"""Request-shape validation -- enforcement band 4 (ERR_INVALID_REQUEST)."""

import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def bad(name, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (name, why))


def parse_datetime(value, name):
    if not isinstance(value, str) or not _DT_RE.match(value.strip()):
        bad(name, "must be an ISO 8601 UTC datetime")
    text = value.strip()
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad(name, "must be an ISO 8601 UTC datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Field(object):
    def __init__(self, kind, required=False, nullable=False, values=None,
                 minimum=None, maximum=None, places=None, min_len=None, max_len=None):
        self.kind = kind
        self.required = required
        self.nullable = nullable
        self.values = values
        self.minimum = minimum
        self.maximum = maximum
        self.places = places
        self.min_len = min_len
        self.max_len = max_len

    def check(self, value, name):
        if value is None:
            if self.nullable:
                return None
            bad(name, "must not be null")
        if self.kind == "str":
            if not isinstance(value, str):
                bad(name, "must be a string")
            if self.min_len is not None and len(value) < self.min_len:
                bad(name, "is shorter than the minimum length")
            if self.max_len is not None and len(value) > self.max_len:
                bad(name, "is longer than the maximum length")
            return value
        if self.kind == "enum":
            if not isinstance(value, str) or value not in self.values:
                bad(name, "is not a declared enum member")
            return value
        if self.kind == "id":
            if not isinstance(value, str) or value == "":
                bad(name, "must be a non-empty identifier string")
            return value
        if self.kind == "bool":
            if not isinstance(value, bool):
                bad(name, "must be a boolean")
            return value
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                bad(name, "must be an integer")
            if self.minimum is not None and value < self.minimum:
                bad(name, "is below the permitted minimum")
            if self.maximum is not None and value > self.maximum:
                bad(name, "is above the permitted maximum")
            return value
        if self.kind == "dec":
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                bad(name, "must be a number")
            try:
                parsed = Decimal(str(value))
            except InvalidOperation:
                bad(name, "must be a number")
            exponent = parsed.as_tuple().exponent
            if self.places is not None and isinstance(exponent, int) and -exponent > self.places:
                bad(name, "carries more decimal places than permitted")
            if self.minimum is not None and parsed < self.minimum:
                bad(name, "is below the permitted minimum")
            if self.maximum is not None and parsed > self.maximum:
                bad(name, "is above the permitted maximum")
            if self.places is not None:
                parsed = parsed.quantize(Decimal(1).scaleb(-self.places))
            return parsed
        if self.kind == "datetime":
            return parse_datetime(value, name)
        raise RuntimeError("unknown field kind %r" % self.kind)


def _raw_body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        bad("request body", "is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        bad("request body", "must be a JSON object")
    return body


def parse_body(spec):
    body = _raw_body()
    for key in body:
        if key not in spec:
            bad(key, "is not a recognised input field")
    out = {}
    for name, field in spec.items():
        if name not in body:
            if field.required:
                bad(name, "is required")
            continue
        out[name] = field.check(body[name], name)
    return out


# ---------------------------------------------------------------- query args

def _coerce_query(field, raw, name):
    if field.kind == "int":
        try:
            value = int(raw)
        except (TypeError, ValueError):
            bad(name, "must be an integer")
        if raw.strip() != str(value):
            # tolerate leading '+' / whitespace but reject float-ish input
            try:
                if float(raw) != value:
                    bad(name, "must be an integer")
            except (TypeError, ValueError):
                bad(name, "must be an integer")
        return field.check(value, name)
    if field.kind == "bool":
        lowered = raw.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        bad(name, "must be true or false")
    if field.kind == "dec":
        try:
            value = Decimal(raw)
        except InvalidOperation:
            bad(name, "must be a number")
        return field.check(value, name)
    return field.check(raw, name)


PAGINATION_SPEC = {
    "limit": Field("int", minimum=1, maximum=100),
    "offset": Field("int", minimum=0),
}


def parse_query(spec, paginated=True):
    full = dict(spec)
    if paginated:
        full.update(PAGINATION_SPEC)
    for key in request.args.keys():
        if key not in full:
            bad(key, "is not a recognised query parameter")
    out = {}
    for name, field in full.items():
        if name not in request.args:
            if field.required:
                bad(name, "is required")
            continue
        out[name] = _coerce_query(field, request.args.get(name), name)
    if paginated:
        out.setdefault("limit", 10)
        out.setdefault("offset", 0)
    return out


def paginate(rows, query):
    limit = query["limit"]
    offset = query["offset"]
    total = len(rows)
    return rows[offset:offset + limit], limit, offset, total
