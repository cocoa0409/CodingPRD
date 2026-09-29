"""Auth header extraction, RBAC, body parsing, schema validation, pagination."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

ROLES = (
    "SystemAdmin",
    "RecruitingCoordinator",
    "ConflictsCounsel",
    "CommitteeChair",
    "CommitteeMember",
    "PracticeGroupLeader",
    "Candidate",
)

READ_ALL = (
    "SystemAdmin", "RecruitingCoordinator", "PracticeGroupLeader",
    "ConflictsCounsel", "CommitteeMember", "CommitteeChair",
)


def authenticate(allowed_roles):
    """PRD 2.1: X-User-ID + X-User-Role. 401 then 403."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


def body():
    """Parsed JSON object body; malformed or non-object bodies are 400."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def bad(field, why):
    return ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


# --------------------------------------------------------------------------
# scalar validators
# --------------------------------------------------------------------------

_MISSING = object()


def _present(data, field, required):
    if field not in data or data[field] is None:
        if required:
            raise bad(field, "is required")
        return _MISSING
    return data[field]


def v_str(data, field, min_len=1, max_len=None, required=True, default=None):
    value = _present(data, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        raise bad(field, "must be a string")
    if min_len is not None and len(value) < min_len:
        raise bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        raise bad(field, "must be at most %d characters" % max_len)
    return value


def v_enum(data, field, allowed, required=True, default=None):
    value = _present(data, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def v_bool(data, field, required=True, default=None):
    value = _present(data, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        raise bad(field, "must be a boolean")
    return value


def v_int(data, field, minimum=None, maximum=None, required=True, default=None):
    value = _present(data, field, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        raise bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        raise bad(field, "must be <= %s" % maximum)
    return value


def v_num(data, field, minimum=None, maximum=None, exclusive_min=False,
          exclusive_max=False, required=True, default=None):
    """Decimal-backed numeric field. JSON numbers only (never strings)."""
    value = _present(data, field, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad(field, "must be a number")
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise bad(field, "must be a number")
    if not dec.is_finite():
        raise bad(field, "must be a finite number")
    if minimum is not None:
        limit = Decimal(str(minimum))
        if exclusive_min and dec <= limit:
            raise bad(field, "must be greater than %s" % minimum)
        if not exclusive_min and dec < limit:
            raise bad(field, "must be >= %s" % minimum)
    if maximum is not None:
        limit = Decimal(str(maximum))
        if exclusive_max and dec >= limit:
            raise bad(field, "must be less than %s" % maximum)
        if not exclusive_max and dec > limit:
            raise bad(field, "must be <= %s" % maximum)
    return dec


def parse_dt(value, field):
    if not isinstance(value, str):
        raise bad(field, "must be an ISO 8601 timestamp string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad(field, "must be an ISO 8601 timestamp string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def v_dt(data, field, required=True, default=None):
    value = _present(data, field, required)
    if value is _MISSING:
        return default
    return parse_dt(value, field)


def v_str_list(data, field, min_items=1, max_items=None, item_min=1,
               item_max=None, distinct=False, required=True, default=None):
    value = _present(data, field, required)
    if value is _MISSING:
        return default
    if not isinstance(value, list):
        raise bad(field, "must be an array of strings")
    if min_items is not None and len(value) < min_items:
        raise bad(field, "must contain at least %d item(s)" % min_items)
    if max_items is not None and len(value) > max_items:
        raise bad(field, "must contain at most %d item(s)" % max_items)
    for item in value:
        if not isinstance(item, str):
            raise bad(field, "must be an array of strings")
        if item_min is not None and len(item) < item_min:
            raise bad(field, "items must be at least %d characters" % item_min)
        if item_max is not None and len(item) > item_max:
            raise bad(field, "items must be at most %d characters" % item_max)
    if distinct and len(set(value)) != len(value):
        raise bad(field, "items must be distinct")
    return list(value)


# --------------------------------------------------------------------------
# pagination (PRD 2.3)
# --------------------------------------------------------------------------

def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            raise bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            raise bad("limit", "must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            raise bad("offset", "must be an integer")
        if offset < 0:
            raise bad("offset", "must be >= 0")
    return limit, offset


def query_bool(name, default=False):
    raw = request.args.get(name)
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise bad(name, "must be a boolean")


def query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        raise bad(name, "must be an integer")
