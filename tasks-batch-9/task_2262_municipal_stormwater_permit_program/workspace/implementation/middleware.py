"""Actor identification, role authorisation, body/query validation.

The helpers here are called in the order dictated by the rejection ladder of
PRD section 2.5: identity (401), role (403), request shape (400), and only
afterwards may a handler resolve path identifiers.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import g, request

from errors import ApiError

# ---------------------------------------------------------------------------
# roles
# ---------------------------------------------------------------------------

MANAGER = "StormwaterProgramManager"
IDDE = "IDDEInvestigator"
INSPECTOR = "ConstructionInspector"
OFFICER = "EnforcementOfficer"
OPS = "MunicipalOperationsSupervisor"
CLERK = "UtilityBillingClerk"
OWNER = "PropertyOwner"

OPERATIONAL_ROLES = [MANAGER, IDDE, INSPECTOR, OFFICER, OPS, CLERK]
ALL_ROLES = OPERATIONAL_ROLES + [OWNER]


def require(roles):
    """Identify the actor and authorise the role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_MISSING_USER_ID", "The X-User-ID header is required.")
    role = request.headers.get("X-User-Role")
    if role not in roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %r may not perform this operation." % (role,))
    g.user_id = user_id
    g.role = role
    return user_id, role


# ---------------------------------------------------------------------------
# body
# ---------------------------------------------------------------------------


def body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    parsed = request.get_json(force=True, silent=True)
    if parsed is None:
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


def _bad(field, why):
    raise ApiError("ERR_VALIDATION", "Field %r %s." % (field, why))


def _present(payload, field):
    return field in payload and payload[field] is not None


# ---------------------------------------------------------------------------
# scalar validators
# ---------------------------------------------------------------------------


def get_str(payload, field, required=True, default=None, min_len=1, max_len=None):
    if not _present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters" % max_len)
    return value


def get_enum(payload, field, allowed, required=True, default=None):
    if not _present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def get_bool(payload, field, required=True, default=None):
    if not _present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def _to_decimal(field, value):
    if isinstance(value, bool):
        _bad(field, "must be a number")
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            _bad(field, "must be a number")
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            _bad(field, "must be a number")
    _bad(field, "must be a number")


def get_number(
    payload,
    field,
    required=True,
    default=None,
    minimum=None,
    maximum=None,
    exclusive_minimum=None,
    exclusive_maximum=None,
):
    if not _present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = _to_decimal(field, payload[field])
    if not value.is_finite():
        _bad(field, "must be a finite number")
    if minimum is not None and value < Decimal(str(minimum)):
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > Decimal(str(maximum)):
        _bad(field, "must be <= %s" % maximum)
    if exclusive_minimum is not None and value <= Decimal(str(exclusive_minimum)):
        _bad(field, "must be > %s" % exclusive_minimum)
    if exclusive_maximum is not None and value >= Decimal(str(exclusive_maximum)):
        _bad(field, "must be < %s" % exclusive_maximum)
    return value


def get_int(payload, field, required=True, default=None, minimum=None, maximum=None):
    if not _present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if isinstance(value, bool):
        _bad(field, "must be an integer")
    if isinstance(value, int):
        number = value
    elif isinstance(value, float):
        if float(value).is_integer():
            number = int(value)
        else:
            _bad(field, "must be an integer")
    elif isinstance(value, str):
        text = value.strip()
        try:
            number = int(text)
        except ValueError:
            _bad(field, "must be an integer")
    else:
        _bad(field, "must be an integer")
    if minimum is not None and number < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and number > maximum:
        _bad(field, "must be <= %s" % maximum)
    return number


def get_date(payload, field, required=True, default=None):
    if not _present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be an ISO 8601 date")
    return parse_date(field, value)


def parse_date(field, value):
    text = value.strip()
    if len(text) != 10:
        _bad(field, "must be an ISO 8601 date (YYYY-MM-DD)")
    try:
        return date.fromisoformat(text)
    except ValueError:
        _bad(field, "must be an ISO 8601 date (YYYY-MM-DD)")


def get_datetime(payload, field, required=True, default=None):
    """Returns (datetime aware in UTC, canonical text) or (None, None)."""
    if not _present(payload, field):
        if required:
            _bad(field, "is required")
        return default, None
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be an ISO 8601 timestamp")
    return parse_datetime(field, value), value


def parse_datetime(field, value):
    text = value.strip()
    if not text:
        _bad(field, "must be an ISO 8601 timestamp")
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        _bad(field, "must be an ISO 8601 timestamp")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# query parameters
# ---------------------------------------------------------------------------


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except ValueError:
            _bad("limit", "must be an integer between 1 and 100")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except ValueError:
            _bad("offset", "must be a non-negative integer")
        if offset < 0:
            _bad("offset", "must be a non-negative integer")
    return limit, offset


def filters(spec):
    """spec: {query_param: (row_key, allowed_values_or_None)} -> {row_key: value}"""
    out = {}
    for param, (row_key, allowed) in spec.items():
        if param not in request.args:
            continue
        value = request.args.get(param)
        if value == "":
            continue
        if allowed is not None and value not in allowed:
            _bad(param, "must be one of %s" % ", ".join(sorted(allowed)))
        out[row_key] = value
    return out


def apply_filters(rows, active):
    if not active:
        return rows
    result = []
    for row in rows:
        keep = True
        for key, value in active.items():
            if row.get(key) != value:
                keep = False
                break
        if keep:
            result.append(row)
    return result
