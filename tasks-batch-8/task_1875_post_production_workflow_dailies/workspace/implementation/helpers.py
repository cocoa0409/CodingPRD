"""Shared helpers: validation, serialization, pagination, derived fields."""

import re
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
)
from clock import clock as logical_clock, format_iso

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def now_iso():
    """Current logical-clock timestamp, ISO 8601 UTC with 3 fractional digits."""
    return format_iso(logical_clock.now())


def touch(entity):
    """Refresh updated_at and increment version on any mutation (PRD §2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1


def new_entity(extra_fields, common=True):
    """Create the common system-managed fields for a new entity."""
    entity = dict(extra_fields)
    entity["id"] = __import__("response").new_id()
    entity["created_at"] = now_iso()
    if common:
        entity["updated_at"] = entity["created_at"]
        entity["version"] = 1
    return entity


# ---------------------------------------------------------------------------
# Body-shape validation (PRD §2.9 step 4)
# ---------------------------------------------------------------------------


def get_json_body():
    """Return the request JSON body; {} when absent. Raise on malformed."""
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Malformed body: request is not valid JSON",
            400,
        )
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Malformed body: expected a JSON object",
            400,
        )
    return body


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool))


def require_fields(body, fields):
    """Verify each named field is present (non-None) in the body."""
    for name in fields:
        if name not in body or body[name] is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"Malformed body: missing required field '{name}'",
                400,
            )


def check_string(body, name, min_len=None, max_len=None):
    value = body[name]
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{name}' must be a string", 400)
    if min_len is not None and len(value) < min_len:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{name}' must be at least {min_len} characters",
            400,
        )
    if max_len is not None and len(value) > max_len:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{name}' must be at most {max_len} characters",
            400,
        )
    return value


def check_int(body, name, min_v=None, max_v=None):
    value = body[name]
    if not _is_int(value):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{name}' must be an integer", 400)
    if min_v is not None and value < min_v:
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' must be at least {min_v}", 400
        )
    if max_v is not None and value > max_v:
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' must be at most {max_v}", 400
        )
    return value


def check_number(body, name, min_v=None, max_v=None):
    value = body[name]
    if not _is_num(value):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{name}' must be a number", 400)
    if min_v is not None and value < min_v:
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' must be at least {min_v}", 400
        )
    if max_v is not None and value > max_v:
        raise ApiError(
            ERR_INVALID_REQUEST, f"Field '{name}' must be at most {max_v}", 400
        )
    return value


def check_enum(body, name, allowed):
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{name}' must be one of {sorted(allowed)}",
            400,
        )
    return value


def check_bool(body, name):
    value = body[name]
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{name}' must be a boolean", 400)
    return value


def check_list(body, name, min_len=None, max_len=None):
    value = body[name]
    if not isinstance(value, list):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{name}' must be an array", 400)
    if min_len is not None and len(value) < min_len:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{name}' must contain at least {min_len} entries",
            400,
        )
    if max_len is not None and len(value) > max_len:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{name}' must contain at most {max_len} entries",
            400,
        )
    return value


def check_datetime_string(body, name):
    value = check_string(body, name)
    try:
        from clock import _parse_iso

        _parse_iso(value)
    except Exception:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{name}' must be an ISO 8601 UTC datetime",
            400,
        )
    return value


def check_date_string(body, name):
    value = check_string(body, name)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{name}' must be a calendar date YYYY-MM-DD",
            400,
        )
    from datetime import date

    try:
        date.fromisoformat(value)
    except ValueError:
        raise ApiError(
            ERR_INVALID_REQUEST,
            f"Field '{name}' must be a valid calendar date YYYY-MM-DD",
            400,
        )
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------


def get_pagination():
    """Parse limit/offset query params with defaults 10/0, bounds 1..100/0.."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError(
                ERR_INVALID_REQUEST, "Query parameter 'limit' must be an integer", 400
            )
        if limit < 1 or limit > 100:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Query parameter 'limit' must be between 1 and 100",
                400,
            )
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError(
                ERR_INVALID_REQUEST, "Query parameter 'offset' must be an integer", 400
            )
        if offset < 0:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Query parameter 'offset' must be at least 0",
                400,
            )
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending, then apply offset/limit window."""
    ordered = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    total = len(ordered)
    window = ordered[offset : offset + limit]
    return window, total


def get_filter(name):
    value = request.args.get(name)
    return value if value not in (None, "") else None


# ---------------------------------------------------------------------------
# Storage calculation (PRD §2.8, §3.2)
# ---------------------------------------------------------------------------

_GIB = 1024 ** 3


def compute_storage_used_gb(project_id, assets):
    """Sum of (source_bytes + proxy_bytes) over non-PURGED assets of the
    project, converted to GiB and rounded half-up to 3 decimal places."""
    total_bytes = 0
    for asset in assets.values():
        if asset["project_id"] != project_id:
            continue
        if asset["status"] == "PURGED":
            continue
        total_bytes += asset["source_bytes"] + asset["proxy_bytes"]
    gib = Decimal(total_bytes) / Decimal(_GIB)
    rounded = gib.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(rounded)
