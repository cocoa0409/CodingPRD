"""Auth header extraction, RBAC, payload validation and pagination helpers.

Refusal ladder rungs 1-4 live here (PRD 2.9):
  1 ERR_MISSING_AUTH_HEADERS  2 ERR_UNKNOWN_ROLE
  3 ERR_UNAUTHORIZED          4 ERR_INVALID_REQUEST
"""

from flask import request

import db
from errors import ApiError, invalid

PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
HOUSING_COMPLIANCE_OFFICER = "HousingComplianceOfficer"
DEVELOPER = "Developer"
RESIDENT = "Resident"
FUND_AUDITOR = "FundAuditor"

ROLES = (
    PROGRAM_ADMINISTRATOR,
    HOUSING_COMPLIANCE_OFFICER,
    DEVELOPER,
    RESIDENT,
    FUND_AUDITOR,
)

ALL_ROLES = ROLES


def auth(*allowed_roles):
    """Rungs 1-3. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    user_id = str(user_id)
    role = str(role)
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# --------------------------------------------------------------------------
# payload helpers (rung 4)
# --------------------------------------------------------------------------
def body():
    """Parse the JSON body; a malformed or non-object body is ERR_INVALID_REQUEST.
    An absent body is treated as an empty object."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid("Request body must be valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object.")
    return parsed


def _present(data, key):
    return key in data and data[key] is not None


def need(data, key):
    if not _present(data, key):
        raise invalid("Field '%s' is required." % key)


def take_int(data, key, required=True, lo=None, hi=None, default=None):
    if not _present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer." % key)
    if lo is not None and value < lo:
        raise invalid("Field '%s' must be >= %s." % (key, lo))
    if hi is not None and value > hi:
        raise invalid("Field '%s' must be <= %s." % (key, hi))
    return value


def take_str(data, key, required=True, min_len=1, max_len=None, default=None):
    if not _present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        raise invalid("Field '%s' must be at least %s characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' must be at most %s characters." % (key, max_len))
    return value


def take_bool(data, key, required=True, default=None):
    if not _present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise invalid("Field '%s' must be a boolean." % key)
    return value


def take_enum(data, key, allowed, required=True, default=None):
    if not _present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        raise invalid("Field '%s' must be one of %s." % (key, sorted(allowed)))
    return value


def take_date(data, key, required=True, default=None):
    """Strict YYYY-MM-DD calendar date; returns the string."""
    if not _present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or db.parse_date(value) is None:
        raise invalid("Field '%s' must be a YYYY-MM-DD date." % key)
    return value.strip()


def take_date_loose(data, key, required=True, default=None):
    """Calendar date, tolerating a full ISO timestamp; returns what was supplied."""
    if not _present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or db.parse_date_loose(value) is None:
        raise invalid("Field '%s' must be an ISO 8601 date." % key)
    return value.strip()


def take_datetime(data, key, required=True, default=None):
    """ISO 8601 instant; returns the canonicalised string."""
    if not _present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return default
    value = data[key]
    parsed = db.parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        raise invalid("Field '%s' must be an ISO 8601 UTC timestamp." % key)
    return db.fmt_dt(parsed)


def take_str_set(data, key, allowed, required=False, default=None, allow_dups=False):
    """A list of unique strings drawn from `allowed`."""
    if not _present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return list(default) if default is not None else []
    value = data[key]
    if not isinstance(value, list):
        raise invalid("Field '%s' must be an array." % key)
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise invalid("Field '%s' entries must be one of %s." % (key, sorted(allowed)))
        if item in seen and not allow_dups:
            raise invalid("Field '%s' must not contain duplicates." % key)
        seen.append(item)
    return seen


def take_int_map(data, key, allowed_keys=None, required_keys=None, lo=None, hi=None,
                 required=True, default=None):
    """An object whose values are integers within [lo, hi]."""
    if not _present(data, key):
        if required:
            raise invalid("Field '%s' is required." % key)
        return dict(default) if default is not None else {}
    value = data[key]
    if not isinstance(value, dict):
        raise invalid("Field '%s' must be an object." % key)
    out = {}
    for map_key, map_value in value.items():
        if allowed_keys is not None and map_key not in allowed_keys:
            raise invalid("Field '%s' has unsupported key '%s'." % (key, map_key))
        if isinstance(map_value, bool) or not isinstance(map_value, int):
            raise invalid("Field '%s' values must be integers." % key)
        if lo is not None and map_value < lo:
            raise invalid("Field '%s' values must be >= %s." % (key, lo))
        if hi is not None and map_value > hi:
            raise invalid("Field '%s' values must be <= %s." % (key, hi))
        out[map_key] = map_value
    if required_keys:
        for needed in required_keys:
            if needed not in out:
                raise invalid("Field '%s' must contain key '%s'." % (key, needed))
    return out


# --------------------------------------------------------------------------
# pagination + filtering
# --------------------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'limit' must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise invalid("Query parameter 'limit' must be between %s and %s."
                          % (LIMIT_MIN, LIMIT_MAX))
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise invalid("Query parameter 'offset' must not be negative.")
    return limit, offset


def _matches(row, field, raw):
    stored = row.get(field)
    if isinstance(stored, bool):
        lowered = raw.strip().lower()
        if lowered in ("true", "1"):
            return stored is True
        if lowered in ("false", "0"):
            return stored is False
        return False
    if stored is None:
        return raw == "" or raw.lower() == "null"
    if isinstance(stored, int):
        try:
            return stored == int(raw)
        except (TypeError, ValueError):
            return False
    if isinstance(stored, list):
        return raw in stored
    return str(stored) == raw


def filtered(store, fields):
    """Apply equality filters for the declared query fields, default sort ASC."""
    rows = db.all_rows(store)
    for field in fields:
        raw = request.args.get(field)
        if raw is None:
            continue
        rows = [row for row in rows if _matches(row, field, raw)]
    return rows


def page(rows, limit, offset):
    return rows[offset:offset + limit]
