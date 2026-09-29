"""Auth header extraction, role gating and request-body validation helpers."""

from flask import request

import db
from errors import ApiError

ROLES = (
    "ProgramAdmin",
    "StateTitleClerk",
    "InsurerAdjuster",
    "Rebuilder",
    "Inspector",
    "HearingOfficer",
    "FraudInvestigator",
)


def authenticate(*allowed_roles):
    """Header presence/validity first, then endpoint role membership."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip() or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# --------------------------------------------------------------------------
# Body / query-parameter helpers.  Every failure here is ERR_INVALID_REQUEST.
# --------------------------------------------------------------------------


def body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def bad(field, why="is invalid"):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def req_str(data, field, max_len=None):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        bad(field, "is required and must be a non-empty string")
    if max_len is not None and len(value) > max_len:
        bad(field, "exceeds the maximum length")
    return value


def opt_str(data, field, default=None, max_len=None):
    if field not in data or data.get(field) is None:
        return default
    value = data.get(field)
    if not isinstance(value, str):
        bad(field, "must be a string")
    if max_len is not None and len(value) > max_len:
        bad(field, "exceeds the maximum length")
    return value


def req_enum(data, field, allowed):
    value = data.get(field)
    if not isinstance(value, str) or value not in allowed:
        bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_enum(data, field, allowed)


def _as_int(field, value):
    if isinstance(value, bool):
        bad(field, "must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    bad(field, "must be an integer")


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data.get(field) is None:
        bad(field, "is required")
    value = _as_int(field, data.get(field))
    if minimum is not None and value < minimum:
        bad(field, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be at most %d" % maximum)
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data.get(field) is None:
        return default
    value = _as_int(field, data.get(field))
    if minimum is not None and value < minimum:
        bad(field, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be at most %d" % maximum)
    return value


def req_bool(data, field):
    value = data.get(field)
    if not isinstance(value, bool):
        bad(field, "is required and must be a boolean")
    return value


def opt_bool(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    value = data.get(field)
    if not isinstance(value, bool):
        bad(field, "must be a boolean")
    return value


def req_dt(data, field):
    """Returns (raw_string, aware_datetime).  The raw string is echoed back."""
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        bad(field, "is required and must be an ISO 8601 instant")
    parsed = db.parse_dt(value)
    if parsed is None:
        bad(field, "must be an ISO 8601 instant")
    return value, parsed


def opt_dt(data, field):
    if field not in data or data.get(field) is None:
        return None, None
    return req_dt(data, field)


def req_state_code(data, field):
    value = req_str(data, field)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        bad(field, "must be exactly two uppercase letters")
    return value


VIN_ALPHABET = set("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")


def req_vin(data, field):
    value = req_str(data, field)
    if len(value) != 17 or any(ch not in VIN_ALPHABET for ch in value):
        bad(field, "must be 17 characters drawn from A-Z (excluding I, O, Q) and 0-9")
    return value


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("limit", "must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            bad("limit", "must be an integer between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("offset", "must be an integer of 0 or greater")
        if offset < 0:
            bad("offset", "must be an integer of 0 or greater")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def bool_filter(name):
    value = filter_value(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad(name, "must be true or false")
