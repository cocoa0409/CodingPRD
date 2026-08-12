"""Shared helpers: id minting, entity lifecycle stamps, body validation."""

import uuid
from decimal import Decimal, InvalidOperation

import clocktime
import db
from errors import ApiError, ERR_VALIDATION


def new_id():
    """Bare UUID, no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_cert_number():
    """CERT-<8 uppercase hex> (SCAFFOLD §1.1 Certificate)."""
    return "CERT-" + uuid.uuid4().hex[:8].upper()


def stamp_new(entity):
    """Attach common system fields to a freshly created primary resource."""
    ts = clocktime.fmt_ts(clocktime.now())
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def stamp_append_only(entity):
    """CustodyEvent / LedgerEntry carry only id + created_at (PRD §2.4)."""
    entity["created_at"] = clocktime.fmt_ts(clocktime.now())
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD §2.4)."""
    entity["updated_at"] = clocktime.fmt_ts(clocktime.now())
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Request body validation helpers (ERR_VALIDATION / 400 on any violation)
# ---------------------------------------------------------------------------

def _fail(message):
    raise ApiError(ERR_VALIDATION, 400, message)


def body_json():
    """Return the request JSON object, requiring a JSON object body."""
    from flask import request
    data = request.get_json(force=True, silent=True)
    if data is None or not isinstance(data, dict):
        _fail("request body must be a JSON object")
    return data


def has_field(data, name):
    return name in data and data[name] is not None


def req_str(data, name):
    v = data.get(name)
    if not isinstance(v, str):
        _fail(f"{name} is required and must be a string")
    return v


def opt_str(data, name):
    if name not in data or data[name] is None:
        return None
    v = data[name]
    if not isinstance(v, str):
        _fail(f"{name} must be a string")
    return v


def req_int(data, name):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(f"{name} is required and must be an integer")
    return v


def opt_int(data, name):
    if name not in data or data[name] is None:
        return None
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(f"{name} must be an integer")
    return v


def req_bool(data, name):
    v = data.get(name)
    if not isinstance(v, bool):
        _fail(f"{name} is required and must be a boolean")
    return v


def opt_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, bool):
        _fail(f"{name} must be a boolean")
    return v


def req_enum(data, name, allowed):
    v = data.get(name)
    if not isinstance(v, str) or v not in allowed:
        _fail(f"{name} must be one of {sorted(allowed)}")
    return v


def req_number(data, name):
    """Numeric JSON value -> Decimal. Rejects bools/strings."""
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _fail(f"{name} is required and must be a number")
    try:
        return Decimal(str(v))
    except InvalidOperation:
        _fail(f"{name} must be a number")


def req_weight(data, name):
    """weight_kg: > 0 and at most three decimal places (PRD §2.7)."""
    d = req_number(data, name)
    if d <= 0:
        _fail(f"{name} must be greater than zero")
    # decimal places check via exponent of the exact decimal form
    exp = d.normalize().as_tuple().exponent
    if exp < -3:
        _fail(f"{name} supports at most three decimal places")
    return d


def req_datetime(data, name):
    v = data.get(name)
    if not isinstance(v, str):
        _fail(f"{name} is required and must be an ISO 8601 datetime string")
    try:
        return clocktime.parse_iso(v)
    except (ValueError, TypeError):
        _fail(f"{name} must be a valid ISO 8601 datetime")


def opt_datetime(data, name):
    if name not in data or data[name] is None:
        return None
    v = data[name]
    if not isinstance(v, str):
        _fail(f"{name} must be an ISO 8601 datetime string")
    try:
        return clocktime.parse_iso(v)
    except (ValueError, TypeError):
        _fail(f"{name} must be a valid ISO 8601 datetime")


def req_enum_list(data, name, allowed):
    v = data.get(name)
    if not isinstance(v, list) or len(v) == 0:
        _fail(f"{name} is required and must be a non-empty array")
    out = []
    for member in v:
        if not isinstance(member, str) or member not in allowed:
            _fail(f"{name} members must be among {sorted(allowed)}")
        if member not in out:
            out.append(member)
    return out
