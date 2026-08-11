"""Time formatting/parsing, half-up rounding, body validation, pagination."""
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

# Pagination (SCAFFOLD response_envelope.pagination_defaults)
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime; None when invalid."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a Decimal-compatible value to whole cents, half up (PRD §2.6)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money_ratio(amount_cents, ratio_str):
    """round_half_up(amount_cents * ratio) with exact decimal arithmetic."""
    return round_half_up(Decimal(amount_cents) * Decimal(ratio_str))


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


_KIND_CHECKS = {
    "str": lambda v: isinstance(v, str),
    "int": _is_int,
    "pos_int": lambda v: _is_int(v) and v > 0,
    "nonneg_int": lambda v: _is_int(v) and v >= 0,
    "str_list": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
}


def _bad(message):
    raise ApiError(ERR_INVALID_REQUEST, 400, message)


def validate_body(spec):
    """Parse and validate the JSON request body.

    spec: {field: (kind, required, enum_or_None)} with kind in
    str/int/pos_int/nonneg_int/str_list/datetime. Unknown fields are rejected,
    missing required fields rejected, type/enum violations rejected
    (ERR_INVALID_REQUEST, 400). Returns the cleaned value dict.
    """
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        body = {}
    else:
        try:
            body = json.loads(raw)
        except Exception:
            _bad("Request body is not valid JSON")
    if not isinstance(body, dict):
        _bad("Request body must be a JSON object")
    unknown = sorted(set(body.keys()) - set(spec.keys()))
    if unknown:
        _bad(f"Unknown field(s): {', '.join(unknown)}")
    out = {}
    for name, rule in spec.items():
        kind, required, enum = rule
        if name not in body:
            if required:
                _bad(f"Missing required field: {name}")
            continue
        v = body[name]
        if kind == "datetime":
            parsed = parse_dt(v)
            if parsed is None:
                _bad(f"Field {name} must be an ISO 8601 datetime string")
            v = parsed
        else:
            check = _KIND_CHECKS[kind]
            if not check(v):
                _bad(f"Field {name} has an invalid value or type")
        if enum is not None and v not in enum:
            _bad(f"Field {name} must be one of: {', '.join(sorted(enum))}")
        out[name] = v
    return out


def pagination_params():
    """Validate limit/offset query params per PRD §2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            _bad(f"limit must be between {PAGE_MIN_LIMIT} and {PAGE_MAX_LIMIT}")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
        if offset < 0:
            _bad("offset must be >= 0")
    return limit, offset
