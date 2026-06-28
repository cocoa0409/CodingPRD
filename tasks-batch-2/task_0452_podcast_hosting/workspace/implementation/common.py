"""Common system fields, input coercion, and pagination helpers.

Common resource fields (PRD §2.4):
  id          server-minted UUID, no type prefix
  created_at  ISO 8601 UTC, 3 fractional digits, set at creation
  updated_at  ISO 8601 UTC, refreshed on every mutation
  version     integer starting at 1, +1 on every mutation

A DownloadEvent is the lone exception: it carries only id + created_at, no
updated_at and no version (PRD §2.4).
"""

import errors
from db import new_id
from timeutil import clock_iso_ms


def new_common():
    """Initial system fields for a resource with full common_fields=true.

    created_at/updated_at record platform time, which is the logical clock
    (PRD §2.9), not the host wall clock.
    """
    ts = clock_iso_ms()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Record a mutation: refresh updated_at and bump version (PRD §2.4, §2.6).

    Recomputing a derived field is itself a mutation, so callers invoke touch on
    every entity a cascade reaches. updated_at is platform (logical-clock) time.
    """
    entity["updated_at"] = clock_iso_ms()
    entity["version"] = entity.get("version", 0) + 1


# ---------------------------------------------------------------------------
# Request-body coercion / validation helpers. Body well-formedness is the
# lowest-priority gate and surfaces as ERR_INVALID_REQUEST (PRD §2.5).
# ---------------------------------------------------------------------------

def require_body(data):
    if data is None or not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_field(data, name):
    if name not in data or data[name] is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: " + name)
    return data[name]


def require_str(data, name):
    val = require_field(data, name)
    if not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be a non-empty string: " + name)
    return val


def require_int(data, name):
    val = require_field(data, name)
    # bool is a subclass of int — reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be an integer: " + name)
    return val


def optional_int(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    val = data[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be an integer: " + name)
    return val


def require_bool(data, name):
    val = require_field(data, name)
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be a boolean: " + name)
    return val


def optional_bool(data, name, default):
    if name not in data or data[name] is None:
        return default
    val = data[name]
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be a boolean: " + name)
    return val


def require_enum(data, name, allowed):
    val = require_str(data, name)
    if val not in allowed:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid enum value for " + name)
    return val


def require_number(data, name):
    """Accept int or float (used for revenue_share_pct)."""
    val = require_field(data, name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be a number: " + name)
    return val


def optional_number(data, name, default):
    if name not in data or data[name] is None:
        return default
    val = data[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field must be a number: " + name)
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Lists default to created_at ASC.
# ---------------------------------------------------------------------------

def parse_pagination(args):
    limit = _parse_pos_int(args.get("limit"), default=10)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    offset = _parse_pos_int(args.get("offset"), default=0)
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_pos_int(raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Pagination parameter must be an integer")


def paginate(items, limit, offset):
    """Return the page slice. items must already be sorted (created_at ASC)."""
    return items[offset:offset + limit]


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["id"]))
