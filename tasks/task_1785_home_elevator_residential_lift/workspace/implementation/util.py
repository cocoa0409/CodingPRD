"""Time, decimal, serialization, and body-validation helpers.

PRD section 2.5: timestamps are ISO 8601 UTC with three fractional digits;
money is dollars at 2 decimal places with round-half-up.
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from errors import ApiError, ERR_INVALID_REQUEST

CENT = Decimal("0.01")


def dec(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def money(x):
    return dec(x).quantize(CENT, rounding=ROUND_HALF_UP)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field="datetime"):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years
        return dt.replace(year=dt.year + years, day=28)


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        elif isinstance(v, Decimal):
            out[k] = float(v)
        else:
            out[k] = v
    return out


def serialize_list(recs):
    return [serialize(r) for r in recs]


# ---------------------------------------------------------------------------
# Request-body validation (validation priority 4): required fields, types,
# enum membership, and unknown-field rejection all yield ERR_INVALID_REQUEST.
# A null value for an optional field is treated as absent.
# ---------------------------------------------------------------------------

def _coerce(name, value, kind, enum):
    if kind == "string":
        if not isinstance(value, str):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be a string")
        if enum is not None and value not in enum:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be one of {sorted(enum)}")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be a number")
        return value
    if kind == "money":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be a number")
        return dec(value)
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be an integer")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be a boolean")
        return value
    if kind == "datetime":
        return parse_dt(value, name)
    if kind == "enum":
        if not isinstance(value, str) or value not in (enum or ()):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be one of {sorted(enum or [])}")
        return value
    if kind == "string_array":
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be an array of strings")
        return list(value)
    if kind == "enum_array":
        if not isinstance(value, list) or any(not isinstance(x, str) or x not in (enum or ()) for x in value):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Field '{name}' must be an array with members of {sorted(enum or [])}")
        return list(value)
    raise AssertionError(f"unknown kind {kind}")


def validate_body(body, spec):
    """spec: dict name -> (kind, required, enum_or_None). Returns cleaned values."""
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    unknown = set(body.keys()) - set(spec.keys())
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Unknown field(s): {', '.join(sorted(unknown))}")
    out = {}
    for name, (kind, required, enum) in spec.items():
        if name not in body or body[name] is None:
            if required:
                raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field '{name}'")
            continue
        out[name] = _coerce(name, body[name], kind, enum)
    return out


def get_json_body():
    from flask import request
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def sorted_by_created(recs):
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))
