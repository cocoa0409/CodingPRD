"""Request-body schema validation, type coercion, pagination parsing.

Tier-3 checks (ERR_VALIDATION / ERR_INVALID_QUANTITY): required fields present,
types valid, enum members valid, no undeclared payload fields.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from errors import err


def parse_datetime(s, field):
    if not isinstance(s, str):
        err("ERR_VALIDATION", f"{field} must be an ISO 8601 datetime string")
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        err("ERR_VALIDATION", f"{field} is not a valid ISO 8601 datetime")
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    # Timestamp comparisons are made at second precision (PRD §2.6)
    return d.astimezone(timezone.utc).replace(microsecond=0)


def to_decimal(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_VALIDATION", f"{field} must be a number")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        err("ERR_VALIDATION", f"{field} must be a number")
    if not d.is_finite():
        err("ERR_VALIDATION", f"{field} must be a finite number")
    return d


def _coerce(name, value, kind, enum):
    if kind == "str":
        if not isinstance(value, str):
            err("ERR_VALIDATION", f"{name} must be a string")
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            err("ERR_VALIDATION", f"{name} must be an integer")
        return value
    if kind == "num":
        return to_decimal(value, name)
    if kind == "bool":
        if not isinstance(value, bool):
            err("ERR_VALIDATION", f"{name} must be a boolean")
        return value
    if kind == "dt":
        return parse_datetime(value, name)
    if kind == "enum":
        if not isinstance(value, str) or value not in enum:
            err("ERR_VALIDATION", f"{name} must be one of {sorted(enum)}")
        return value
    raise AssertionError(f"unknown kind {kind}")


def body_obj(body):
    if body is None:
        return {}
    if not isinstance(body, dict):
        err("ERR_VALIDATION", "request body must be a JSON object")
    return body


def validate_schema(body, spec):
    """spec: list of (name, kind, required, enum_values_or_None).

    Rejects undeclared fields, missing required fields, bad types/enums with
    ERR_VALIDATION. Returns a dict of coerced values (missing optional -> None).
    """
    body = body_obj(body)
    allowed = {s[0] for s in spec}
    for k in body:
        if k not in allowed:
            err("ERR_VALIDATION", f"unknown field: {k}")
    out = {}
    for name, kind, required, enum in spec:
        if name not in body or body[name] is None:
            if required:
                err("ERR_VALIDATION", f"{name} is required")
            out[name] = None
            continue
        out[name] = _coerce(name, body[name], kind, enum)
    return out


def parse_pagination(args):
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", "limit must be an integer")
        if str(raw_limit).strip() != str(limit) or limit < 1 or limit > 100:
            err("ERR_VALIDATION", "limit must be an integer between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", "offset must be an integer")
        if str(raw_offset).strip() != str(offset) or offset < 0:
            err("ERR_VALIDATION", "offset must be a non-negative integer")
    return limit, offset


def paginate(recs, limit, offset):
    return recs[offset:offset + limit]
