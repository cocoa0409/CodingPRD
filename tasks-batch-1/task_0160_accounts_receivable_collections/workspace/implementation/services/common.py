"""Shared helpers: common-field stamping, input parsing, pagination, enums."""
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ENUM,
    ERR_PAGINATION_INVALID,
    ERR_VALIDATION,
)


# ---------------------------------------------------------------------------
# Common system-managed fields (PRD §2.4).
# ---------------------------------------------------------------------------
def stamp_create(record, with_version=True):
    """Set id/created_at/updated_at/version on a new durable record."""
    ts = db.iso_now()
    record["id"] = db.new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    if with_version:
        record["version"] = 1
    return record


def touch(record):
    """Mutation bookkeeping: refresh updated_at and increment version."""
    record["updated_at"] = db.iso_now()
    if "version" in record:
        record["version"] = record["version"] + 1


def stamp_light(record):
    """DunningNotice / immutable audit records carry only id + created_at."""
    record["id"] = db.new_id()
    record["created_at"] = db.iso_now()
    return record


# ---------------------------------------------------------------------------
# Body / field parsing.
# ---------------------------------------------------------------------------
def get_json_body():
    from flask import request

    if request.method in ("POST", "PUT", "PATCH"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise err(ERR_INVALID_REQUEST, "malformed JSON")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
        return data
    return {}


def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "missing required field: %s" % field)
    return body[field]


def require_int(body, field, minimum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, "field %s must be an integer" % field)
    if minimum is not None and val < minimum:
        raise err(ERR_VALIDATION, "field %s must be >= %d" % (field, minimum))
    return val


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val.strip() == "":
        raise err(ERR_INVALID_REQUEST, "field %s must be a non-empty string" % field)
    return val


def require_enum(body, field, members):
    val = require(body, field)
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, "field %s must be a string" % field)
    if val not in members:
        raise err(ERR_INVALID_ENUM, "field %s has invalid enum value: %s" % (field, val))
    return val


def optional_enum(body, field, members, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, "field %s must be a string" % field)
    if val not in members:
        raise err(ERR_INVALID_ENUM, "field %s has invalid enum value: %s" % (field, val))
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3).
# ---------------------------------------------------------------------------
def parse_pagination():
    from flask import request

    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(ERR_PAGINATION_INVALID, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_PAGINATION_INVALID, "limit out of bounds [1,100]")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(ERR_PAGINATION_INVALID, "offset must be an integer")
        if offset < 0:
            raise err(ERR_PAGINATION_INVALID, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items already sorted; return the page window."""
    return items[offset:offset + limit]


# ---------------------------------------------------------------------------
# Money rounding (PRD §2.10): half up.
# ---------------------------------------------------------------------------
def round_half_up_int(value):
    """Round a numeric value half-up to a whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(value):
    """Round to two decimal places half-up, return a float."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
