"""Shared entity scaffolding: common fields, mutation bookkeeping, pagination,
serialization, and request-body parsing helpers (PRD §2.3, §2.4, §3.9)."""
from flask import request

import db
import errors
import util

# Fields kept internally on every row but NOT serialized to clients.
_INTERNAL_FIELDS = {"_seq"}


def common_fields():
    """Mint id/created_at/updated_at/version + internal sort sequence (PRD §2.4).

    version begins at 1 (its initial value) and increments by one on each mutation.
    """
    ts = util.iso_now()
    return {
        "id": util.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """Record a mutation: refresh updated_at and increment version (PRD §2.4)."""
    row["updated_at"] = util.iso_now()
    row["version"] = row["version"] + 1


def serialize(row):
    """Strip internal fields for the response body."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if k not in _INTERNAL_FIELDS}


# --------------------------------------------------------------------------- #
# Request body helpers
# --------------------------------------------------------------------------- #
def get_body():
    """Return the parsed JSON body as a dict (empty dict if none/invalid)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def require(body, field):
    """Return body[field] or raise ERR_INVALID_REQUEST when missing/None."""
    if field not in body or body[field] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return body[field]


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return val


def require_int(body, field, minimum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    return val


def optional_int(body, field, default, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and val < minimum:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return val


def require_datetime(body, field):
    """Required ISO 8601 datetime; raise ERR_INVALID_REQUEST when missing/malformed."""
    val = require(body, field)
    dt = util.parse_iso(val)
    if dt is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 datetime")
    return dt


# --------------------------------------------------------------------------- #
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------- #
def parse_pagination():
    """Read limit/offset query params with defaults and bounds (PRD §2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def paginate(rows):
    """Sort by creation order ascending, slice, and serialize (PRD §2.3)."""
    limit, offset = parse_pagination()
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total_count = len(ordered)
    window = ordered[offset:offset + limit]
    return [serialize(r) for r in window], limit, offset, total_count
