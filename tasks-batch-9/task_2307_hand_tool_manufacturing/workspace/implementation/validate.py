"""Auth, request-shape and pagination validation helpers (PRD §2.1, §2.3, §2.7)."""

from datetime import datetime, timezone

from flask import request

from errors import ApiError
from store import store

ROLES = [
    "ChannelManager",
    "ProductionPlanner",
    "QualityEngineer",
    "WarrantyAdministrator",
    "BrandProtectionAnalyst",
    "Claimant",
    "PlatformAdmin",
]


def auth(*allowed_roles):
    """Rung 1 + 2 of the ladder. Returns (role, user_id)."""
    role = request.headers.get("X-User-Role")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return role, request.headers.get("X-User-ID")


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


# --------------------------------------------------------------------------- #
# scalar field validation (ERR_INVALID_REQUEST)
# --------------------------------------------------------------------------- #
def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def req_str(body, name, min_len=1, max_len=None):
    value = body.get(name)
    if not isinstance(value, str):
        _bad(name, "is required and must be a string")
    if len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def req_int(body, name, minimum=None, maximum=None):
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "is required and must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %d" % maximum)
    return value


def req_enum(body, name, allowed):
    value = body.get(name)
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def req_str_array(body, name, allowed=None):
    value = body.get(name)
    if not isinstance(value, list) or not value:
        _bad(name, "must be a non-empty array")
    for item in value:
        if not isinstance(item, str):
            _bad(name, "must contain only strings")
        if allowed is not None and item not in allowed:
            _bad(name, "must contain only %s" % ", ".join(allowed))
    return list(value)


def req_number_array(body, name):
    value = body.get(name)
    if not isinstance(value, list):
        _bad(name, "is required and must be an array of numbers")
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            _bad(name, "must contain only numbers")
    return value


def require_present(row, name):
    """Used for body reference fields whose existence lookup already ran."""
    if row is None:
        _bad(name, "is required and must reference an existing resource")
    return row


# --------------------------------------------------------------------------- #
# body reference resolution (existence rung — 404 family)
# --------------------------------------------------------------------------- #
def resolve_ref(body, name, table, error_id):
    """Resolve a body reference. Returns the row, or None when the field is
    absent / null / not a usable string (deferred to the request-shape rung)."""
    value = body.get(name)
    if not isinstance(value, str) or value == "":
        return None
    row = table.get(value)
    if row is None:
        raise ApiError(error_id)
    return row


def resolve_optional_ref(body, name, table, error_id):
    """Optional, nullable reference. Returns (present, row)."""
    if name not in body:
        return False, None
    value = body.get(name)
    if value is None:
        return True, None
    if not isinstance(value, str) or value == "":
        _bad(name, "must be a string identifier or null")
    row = table.get(value)
    if row is None:
        raise ApiError(error_id)
    return True, row


def lookup(table, row_id, error_id):
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


# --------------------------------------------------------------------------- #
# pagination
# --------------------------------------------------------------------------- #
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if str(limit) != raw_limit.strip():
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if str(offset) != raw_offset.strip():
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)


# --------------------------------------------------------------------------- #
# timestamps / windows
# --------------------------------------------------------------------------- #
def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Returns an aware datetime or None."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def window_fields(body):
    """Validate window_start / window_end (rung 300 then 320)."""
    raw_start = body.get("window_start")
    raw_end = body.get("window_end")
    if not isinstance(raw_start, str):
        _bad("window_start", "is required and must be an ISO 8601 UTC instant")
    if not isinstance(raw_end, str):
        _bad("window_end", "is required and must be an ISO 8601 UTC instant")
    start = parse_instant(raw_start)
    end = parse_instant(raw_end)
    if start is None or end is None:
        raise ApiError("ERR_INVALID_WINDOW")
    if start.second != 0 or start.microsecond != 0 or end.second != 0 or end.microsecond != 0:
        raise ApiError("ERR_INVALID_WINDOW")
    if not start < end:
        raise ApiError("ERR_INVALID_WINDOW")
    return start, end, raw_start, raw_end


def filter_arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def bool_filter_arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def claimant_identity(role, user_id):
    """Rung 3: a Claimant caller's X-User-ID must name a Claimant row."""
    if role != "Claimant":
        return None
    if not user_id or user_id not in store.claimants:
        raise ApiError("ERR_CLAIMANT_MISMATCH")
    return store.claimants[user_id]
