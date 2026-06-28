"""Shared helpers: system fields, round-half-up, body validation primitives."""

from decimal import Decimal, ROUND_HALF_UP

import db
import errors
from response import now_iso


def round_half_up(value):
    """Round a numeric value (int/float/Decimal) to the nearest whole cent,
    halves rounding up. Returns an int."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def stamp_common(record, with_version=True):
    """Attach id/created_at/updated_at/version on creation."""
    ts = now_iso()
    record["id"] = db.new_id()
    record["created_at"] = ts
    record["_seq"] = db.next_seq()
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def stamp_audit(record):
    """Attach id/created_at only (Verification, LedgerEntry are immutable)."""
    record["id"] = db.new_id()
    record["created_at"] = now_iso()
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version on mutation."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def public(record):
    """Strip internal-only keys (those prefixed '_') before serialising."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# --- body field extraction / validation -----------------------------------
def require_body(body):
    if body is None or not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def req_str(body, field):
    if field not in body:
        raise errors.invalid_request(f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return val


def req_int(body, field, positive=False):
    if field not in body:
        raise errors.invalid_request(f"Missing required field: {field}")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    if positive and val <= 0:
        raise errors.invalid_request(f"Field {field} must be greater than zero")
    return val


def req_number(body, field):
    if field not in body:
        raise errors.invalid_request(f"Missing required field: {field}")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number")
    return val


def opt_str_default(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string")
    return val


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number")
    return val


def opt_int(body, field, default=None, positive=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer")
    if positive and val <= 0:
        raise errors.invalid_request(f"Field {field} must be greater than zero")
    return val


def req_enum(body, field, allowed):
    val = req_str(body, field)
    if val not in allowed:
        raise errors.invalid_request(
            f"Field {field} must be one of {sorted(allowed)}")
    return val


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request(
            f"Field {field} must be one of {sorted(allowed)}")
    return val


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return val


def req_bool(body, field):
    if field not in body:
        raise errors.invalid_request(f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, bool):
        raise errors.invalid_request(f"Field {field} must be a boolean")
    return val


def req_datetime(body, field):
    """Require an ISO 8601 datetime string; returns the parsed UTC datetime."""
    raw = req_str(body, field)
    try:
        return db.parse_iso(raw)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"Field {field} must be an ISO 8601 datetime")


def req_str_list(body, field):
    if field not in body:
        raise errors.invalid_request(f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
        raise errors.invalid_request(f"Field {field} must be an array of strings")
    return val
