"""Validation primitives, pagination, common-field management, serialization."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import db
from errors import ApiError


# ---------------------------------------------------------------------------
# Common fields (PRD §2.4)
# ---------------------------------------------------------------------------
def stamp_create(record, ledger=False):
    """Set id/created_at and, for full entities, updated_at/version=1."""
    record["id"] = db.new_id()
    record["created_at"] = db.now_iso()
    record["_seq"] = db.next_seq()
    if not ledger:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Mutation bump: refresh updated_at, increment version by 1."""
    record["updated_at"] = db.now_iso()
    record["version"] = record.get("version", 1) + 1


def public(record):
    """Strip internal-only keys for output."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Body parsing & field validation (priority 6 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        if request.data and len(request.data) > 0:
            try:
                data = request.get_json(force=True, silent=True)
            except Exception:
                data = None
            if data is None:
                raise ApiError("ERR_INVALID_REQUEST", "Body must be valid JSON.")
            if not isinstance(data, dict):
                raise ApiError("ERR_INVALID_REQUEST", "Body must be a JSON object.")
            return data
        return {}
    return {}


def require_str(body, key):
    if key not in body or not isinstance(body[key], str) or body[key] == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be a non-empty string.")
    return body[key]


def optional_str(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    if not isinstance(body[key], str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be a string.")
    return body[key]


def require_int(body, key, minimum=None, maximum=None):
    if key not in body or isinstance(body[key], bool) or not isinstance(body[key], int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be an integer.")
    val = body[key]
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be <= {maximum}.")
    return val


def optional_int(body, key, default=None, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        return default
    if isinstance(body[key], bool) or not isinstance(body[key], int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be an integer.")
    val = body[key]
    if minimum is not None and val < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be >= {minimum}.")
    if maximum is not None and val > maximum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be <= {maximum}.")
    return val


def require_bool(body, key, default=None):
    if key not in body or body[key] is None:
        if default is not None:
            return default
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' is required.")
    if not isinstance(body[key], bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be a boolean.")
    return body[key]


def require_enum(body, key, domain):
    val = require_str(body, key)
    if val not in domain:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be one of {sorted(domain)}.")
    return val


def optional_enum(body, key, domain, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str) or val not in domain:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be one of {sorted(domain)}.")
    return val


def require_email(body, key):
    val = require_str(body, key)
    if "@" not in val:
        raise ApiError("ERR_INVALID_REQUEST", "Email must contain '@'.")
    return val


def require_datetime(body, key):
    val = require_str(body, key)
    try:
        return db._parse_iso(val)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", f"Field '{key}' must be an ISO 8601 datetime.")


# ---------------------------------------------------------------------------
# Existence resolution (priority 4 -> ERR_NOT_FOUND)
# ---------------------------------------------------------------------------
def must_exist(store, rid):
    if rid is None or rid not in store:
        raise ApiError("ERR_NOT_FOUND", "Referenced resource does not exist.")
    return store[rid]


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3 -> ERR_INVALID_PAGINATION)
# ---------------------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0.")
    return limit, offset


def paginate(records):
    """Sort by creation order ascending, apply limit/offset, return slice + total."""
    limit, offset = pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    sliced = ordered[offset:offset + limit]
    return [public(r) for r in sliced], limit, offset, total


# ---------------------------------------------------------------------------
# Rounding (PRD §2.8): round half up on basis-point terms.
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator):
    """Round numerator/denominator half up to the nearest integer."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)
