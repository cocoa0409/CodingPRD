"""Shared record helpers: IDs, timestamps, serializers, date parsing."""

import uuid
from datetime import date, datetime

import db as dbmod
from errors import raise_err, ERR_VALIDATION


def new_id():
    return str(uuid.uuid4())


def stamp_new(record):
    ts = dbmod.logical_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    record["updated_at"] = dbmod.logical_iso()


def bump(record):
    record["version"] = record.get("version", 1) + 1
    touch(record)


def parse_iso_date(value, field):
    """Parse an ISO date (YYYY-MM-DD or full ISO-8601 datetime); returns date."""
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, f"{field} must be an ISO date string")
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise_err(ERR_VALIDATION, f"{field} is not a valid ISO date")


def parse_iso_datetime(value, field):
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, f"{field} must be an ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err(ERR_VALIDATION, f"{field} is not a valid ISO-8601 instant")
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def req_str(body, field):
    v = body.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise_err(ERR_VALIDATION, f"{field} is required and must be a non-empty string")
    return v


def req_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_VALIDATION, f"{field} is required and must be an integer")
    return v


def opt_int(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_VALIDATION, f"{field} must be an integer")
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, f"{field} is required and must be a boolean")
    return v


def opt_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, f"{field} must be a boolean")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise_err(ERR_VALIDATION, f"{field} must be one of {sorted(allowed)}")
    return v


def req_number(body, field):
    from decimal import Decimal, InvalidOperation
    v = body.get(field)
    if isinstance(v, bool) or v is None:
        raise_err(ERR_VALIDATION, f"{field} is required and must be a number")
    if isinstance(v, (int, float)):
        try:
            return Decimal(str(v))
        except InvalidOperation:
            raise_err(ERR_VALIDATION, f"{field} must be a number")
    raise_err(ERR_VALIDATION, f"{field} must be a number")


def number_out(dec):
    """Render a Decimal as an int when integral, else as float with exact 2dp semantics."""
    from decimal import Decimal
    if not isinstance(dec, Decimal):
        return dec
    if dec == dec.to_integral_value():
        return int(dec)
    return float(dec)
