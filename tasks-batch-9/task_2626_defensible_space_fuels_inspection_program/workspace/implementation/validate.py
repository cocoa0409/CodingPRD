"""Rungs 3, 5 and 6 of the screening ladder: existence, request shape, windows."""

import datetime
from decimal import Decimal, InvalidOperation

from flask import request

from db import db
from errors import fail

UTC = datetime.timezone.utc

_MISSING = object()


# --- rung 3: body foreign keys, resolved in the declaration order of PRD 2.6 --
FK_ORDER = (
    ("cycle_id", "cycles", "ERR_CYCLE_NOT_FOUND"),
    ("parcel_id", "parcels", "ERR_PARCEL_NOT_FOUND"),
    ("community_id", "communities", "ERR_COMMUNITY_NOT_FOUND"),
    ("inspector_id", "inspectors", "ERR_INSPECTOR_NOT_FOUND"),
    ("contractor_id", "contractors", "ERR_CONTRACTOR_NOT_FOUND"),
    ("inspection_id", "inspections", "ERR_INSPECTION_NOT_FOUND"),
    ("violation_notice_id", "notices", "ERR_NOTICE_NOT_FOUND"),
    ("support_program_id", "programs", "ERR_PROGRAM_NOT_FOUND"),
)


def resolve_fks(body, keys):
    """Resolve the named body FKs in declaration order; first miss decides."""
    resolved = {}
    for key, collection, error_id in FK_ORDER:
        if key not in keys:
            continue
        value = body.get(key)
        if value is None:
            continue
        record = getattr(db, collection).get(value) if isinstance(value, str) else None
        if record is None:
            fail(error_id, "No such %s: %r." % (key, value))
        resolved[key] = record
    return resolved


def lookup(collection, identifier, error_id):
    """Rung 3 for a path segment."""
    record = getattr(db, collection).get(identifier)
    if record is None:
        fail(error_id, "No such resource: %r." % (identifier,))
    return record


# --- rung 5: request shape ---------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _present(b, key, required):
    if key not in b or b[key] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return False
    return True


def get_str(b, key, required=True, allow_empty=True, default=None):
    if not _present(b, key, required):
        return default
    value = b[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if not allow_empty and not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-empty." % key)
    return value


def get_enum(b, key, members, required=True, default=None):
    if not _present(b, key, required):
        return default
    value = b[key]
    if not isinstance(value, str) or value not in members:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s." % (key, ", ".join(members)),
        )
    return value


def get_bool(b, key, required=True, default=None):
    if not _present(b, key, required):
        return default
    value = b[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def get_int(b, key, required=True, minimum=None, maximum=None, default=None):
    if not _present(b, key, required):
        return default
    value = b[key]
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if isinstance(value, int):
        result = value
    elif isinstance(value, float) and float(value).is_integer():
        result = int(value)
    else:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if minimum is not None and result < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and result > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (key, maximum))
    return result


def get_decimal(b, key, required=True, minimum=None, maximum=None, default=None,
                max_places=None):
    if not _present(b, key, required):
        return default
    value = b[key]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    if not result.is_finite():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a finite number." % key)
    if minimum is not None and result < Decimal(str(minimum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and result > Decimal(str(maximum)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (key, maximum))
    if max_places is not None and -result.as_tuple().exponent > max_places:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' carries at most %d decimal places." % (key, max_places),
        )
    return result


def get_half_hours(b, key, required=True, default=None):
    """Crew-hour quantities: strictly positive multiples of one half hour."""
    value = get_decimal(b, key, required=required, default=default)
    if value is None:
        return None
    if value <= 0 or (value * 2) % 1 != 0:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be a positive multiple of 0.5." % key,
        )
    return value


def parse_dt(text):
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def get_dt(b, key, required=True, default=None):
    if not _present(b, key, required):
        return default
    parsed = parse_dt(b[key])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 UTC datetime." % key)
    return parsed


# --- rung 6: window orientation ----------------------------------------------
def check_window(start, end):
    if start is not None and end is not None and end <= start:
        fail("ERR_INVALID_TIME_WINDOW", "Window end must be strictly later than its start.")


# --- pagination (PRD section 2.3) --------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def page(records, limit, offset):
    return records[offset:offset + limit]
