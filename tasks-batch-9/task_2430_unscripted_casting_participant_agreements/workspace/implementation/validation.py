"""Admission-ladder helpers: auth (rungs 1-4), body shape (rung 7) and
pagination (rung 8) of PRD §2.6.
"""

from flask import request

from clock import parse_date, parse_iso
from envelope import (
    PAGINATION_LIMIT_DEFAULT,
    PAGINATION_LIMIT_MAX,
    PAGINATION_LIMIT_MIN,
    PAGINATION_OFFSET_DEFAULT,
)
from errors import ApiError

ROLES = (
    "ProductionAdmin",
    "CastingDirector",
    "ComplianceOfficer",
    "BusinessAffairs",
    "WelfareOfficer",
    "Applicant",
)

ALL_ROLES = ROLES
OPERATOR_ROLES = (
    "ProductionAdmin",
    "CastingDirector",
    "ComplianceOfficer",
    "BusinessAffairs",
    "WelfareOfficer",
)


# --------------------------------------------------------------------- auth
def authenticate(allowed_roles):
    """Rungs 1-3: header presence, known role, endpoint role list."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_FORBIDDEN")
    return user_id, role


def require_owner(role, user_id, owner_applicant_id):
    """Rung 4: an Applicant caller may only address their own records."""
    if role != "Applicant":
        return
    if owner_applicant_id is None:
        return
    if user_id != owner_applicant_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# --------------------------------------------------------------------- body
def json_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def _present(body, field):
    return field in body and body[field] is not None


def req_string(body, field, min_len=1, max_len=None):
    if not _present(body, field):
        _bad(field, "is required")
    value = body[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters" % max_len)
    return value


def opt_string(body, field, default=None, min_len=1, max_len=None):
    if not _present(body, field):
        return default
    return req_string(body, field, min_len=min_len, max_len=max_len)


def req_enum(body, field, allowed):
    value = req_string(body, field)
    if value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, field, allowed, default=None):
    if not _present(body, field):
        return default
    return req_enum(body, field, allowed)


def req_int(body, field, minimum=None, maximum=None):
    if not _present(body, field):
        _bad(field, "is required")
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %d" % maximum)
    return value


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if not _present(body, field):
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_number(body, field, minimum=None, maximum=None):
    if not _present(body, field):
        _bad(field, "is required")
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def opt_number(body, field, default=None, minimum=None, maximum=None):
    if not _present(body, field):
        return default
    return req_number(body, field, minimum=minimum, maximum=maximum)


def req_bool(body, field):
    if not _present(body, field):
        _bad(field, "is required")
    value = body[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def opt_bool(body, field, default=None):
    if not _present(body, field):
        return default
    return req_bool(body, field)


def req_datetime(body, field):
    value = req_string(body, field)
    try:
        parse_iso(value)
    except Exception:
        _bad(field, "must be an ISO 8601 datetime")
    return value


def opt_datetime(body, field, default=None):
    if not _present(body, field):
        return default
    return req_datetime(body, field)


def req_date(body, field):
    value = req_string(body, field)
    try:
        parse_date(value)
    except Exception:
        _bad(field, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
    return value


def opt_date(body, field, default=None):
    if not _present(body, field):
        return default
    return req_date(body, field)


def req_id_list(body, field, max_entries=None):
    if not _present(body, field):
        _bad(field, "is required")
    value = body[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    if max_entries is not None and len(value) > max_entries:
        _bad(field, "must hold at most %d entries" % max_entries)
    for entry in value:
        if not isinstance(entry, str) or entry == "":
            _bad(field, "must hold non-empty string ids")
    if len(set(value)) != len(value):
        _bad(field, "must not hold duplicate entries")
    return value


def require_after(body, later_field, earlier_field, later_value, earlier_value):
    """Datetime pair ordering: later strictly after earlier."""
    if later_value is None or earlier_value is None:
        return
    if parse_iso(later_value) <= parse_iso(earlier_value):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be strictly after '%s'." % (later_field, earlier_field),
        )


# --------------------------------------------------------------- pagination
def pagination():
    """Rung 8: 1 <= limit <= 100, offset >= 0."""
    args = request.args
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(records, limit, offset):
    return records[offset:offset + limit]


def filter_arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
