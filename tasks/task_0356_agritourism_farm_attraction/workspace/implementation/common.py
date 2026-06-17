"""Shared primitives: common-field management, datetime parsing, validation,
pagination, and the round-half-up money helper."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

import db
from errors import ApiError


# --------------------------------------------------------------------------- #
# Common system fields (PRD §2.4)
# --------------------------------------------------------------------------- #
def stamp_create(entity, with_version=True):
    """Set id/created_at/updated_at/version on a freshly created entity dict.

    WeatherEvent passes with_version=False — it carries only id + created_at
    (append-only log, never mutated; no updated_at, no version) per PRD §2.4.
    """
    ts = db.iso_now()
    entity["id"] = db.new_id()
    entity["created_at"] = ts
    entity["_seq"] = db.next_seq()
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    """A mutation refreshes updated_at and bumps version (PRD §2.4)."""
    if "version" in entity:
        entity["updated_at"] = db.iso_now()
        entity["version"] += 1


# --------------------------------------------------------------------------- #
# Money: round-half-up to whole cents (PRD §2.7)
# --------------------------------------------------------------------------- #
def round_half_up_cents(value):
    """value (Decimal/number) -> int cents using round-half-up."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_cents(value):
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_CEILING))


# --------------------------------------------------------------------------- #
# Datetime parsing (ISO 8601)
# --------------------------------------------------------------------------- #
def parse_dt(value, field_name):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", f"{field_name} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", f"{field_name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------- #
# Basic body / field validation (PRD §2.7 -> ERR_VALIDATION)
# --------------------------------------------------------------------------- #
def require_body(body):
    if body is None or not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def get_required(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", f"Missing required field: {name}")
    return body[name]


def as_int(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", f"{name} must be <= {maximum}")
    return value


def as_number(value, name, gt=None, ge=None, lt=None, le=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", f"{name} must be a number")
    v = float(value)
    if gt is not None and not v > gt:
        raise ApiError("ERR_VALIDATION", f"{name} must be > {gt}")
    if ge is not None and not v >= ge:
        raise ApiError("ERR_VALIDATION", f"{name} must be >= {ge}")
    if lt is not None and not v < lt:
        raise ApiError("ERR_VALIDATION", f"{name} must be < {lt}")
    if le is not None and not v <= le:
        raise ApiError("ERR_VALIDATION", f"{name} must be <= {le}")
    return value


def as_str(value, name):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_VALIDATION", f"{name} must be a non-empty string")
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError("ERR_VALIDATION", f"{name} must be a boolean")
    return value


def as_enum(value, name, allowed):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", f"{name} must be one of {sorted(allowed)}")
    return value


# --------------------------------------------------------------------------- #
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------- #
def parse_pagination(args):
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(rows, args, newest_first=False):
    """Sort by created_at asc (default) or newest-first, then page."""
    limit, offset = parse_pagination(args)
    rows = sorted(rows, key=lambda r: r["_seq"], reverse=newest_first)
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total
