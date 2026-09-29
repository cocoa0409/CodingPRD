"""Authentication / RBAC (PRD section 2.1) and the validation ladder helpers."""
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import request

from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "Consignor",
    "IntakeInspector",
    "ComplianceOfficer",
    "AuctionOperator",
    "SettlementOfficer",
    "Bidder",
)
ANY_ROLE = ROLES

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Ladder rung 1 — ERR_UNAUTHENTICATED (401), before any body parsing."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "Missing %s header." % USER_ID_HEADER)
    if not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "Missing or unrecognised %s header." % USER_ROLE_HEADER,
        )
    return Actor(str(user_id), role)


def endpoint(*roles):
    """Decorator applying rung 1 (auth) then rung 2 (role) to a handler."""
    allowed = tuple(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor = authenticate()
            if actor.role not in allowed:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "Role %s may not call this endpoint." % actor.role,
                )
            return fn(actor, *args, **kwargs)

        return wrapper

    return decorator


def require_owner(actor, owner_id):
    """Ladder rung 6 — ERR_NOT_RESOURCE_OWNER (403)."""
    if actor.user_id != owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# --------------------------------------------------------------------------
# Body / query validation — ladder rung 3, ERR_INVALID_REQUEST (400)
# --------------------------------------------------------------------------
_MISSING = object()

ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "%s: %s" % (field, why))


def json_body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def parse_iso(value, field):
    if not isinstance(value, str):
        bad(field, "must be an ISO-8601 datetime string")
    m = ISO_RE.match(value.strip())
    if not m:
        bad(field, "must be an ISO-8601 datetime string")
    year, month, day, hour, minute, second, frac, offset = m.groups()
    try:
        micro = 0
        if frac:
            micro = int(round(float(frac) * 1000000))
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second or 0), micro, tzinfo=timezone.utc,
        )
    except ValueError:
        bad(field, "is not a valid calendar instant")
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        dt = dt - sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return dt


def field_str(body, name, required=False, min_len=None, max_len=None,
              default=None, nullable=False, pattern=None, upper=False):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        if required:
            bad(name, "is required")
        return default
    if value is None:
        if nullable:
            return None
        bad(name, "may not be null")
    if not isinstance(value, str):
        bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        bad(name, "must be at most %d characters" % max_len)
    if upper and value != value.upper():
        bad(name, "must be upper case")
    if pattern is not None and not re.match(pattern, value):
        bad(name, "does not match the required format")
    return value


def field_int(body, name, required=False, min_value=None, max_value=None,
              default=None, nullable=False):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        if required:
            bad(name, "is required")
        return default
    if value is None:
        if nullable:
            return None
        bad(name, "may not be null")
    if isinstance(value, bool) or not isinstance(value, int):
        bad(name, "must be an integer")
    if min_value is not None and value < min_value:
        bad(name, "must be >= %d" % min_value)
    if max_value is not None and value > max_value:
        bad(name, "must be <= %d" % max_value)
    return value


def field_bool(body, name, required=False, default=None, nullable=False):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        if required:
            bad(name, "is required")
        return default
    if value is None:
        if nullable:
            return None
        bad(name, "may not be null")
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def field_decimal(body, name, required=False, min_value=None, max_value=None,
                  max_decimals=None, default=None, nullable=False):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        if required:
            bad(name, "is required")
        return default
    if value is None:
        if nullable:
            return None
        bad(name, "may not be null")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(name, "must be a number")
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        bad(name, "must be a number")
    if min_value is not None and dec < Decimal(str(min_value)):
        bad(name, "must be >= %s" % min_value)
    if max_value is not None and dec > Decimal(str(max_value)):
        bad(name, "must be <= %s" % max_value)
    if max_decimals is not None:
        exponent = dec.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_decimals:
            bad(name, "may carry at most %d decimal place(s)" % max_decimals)
    return dec


def field_enum(body, name, allowed, required=False, default=None, nullable=False):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        if required:
            bad(name, "is required")
        return default
    if value is None:
        if nullable:
            return None
        bad(name, "may not be null")
    if not isinstance(value, str) or value not in allowed:
        bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def field_dt(body, name, required=False, default=None, nullable=False):
    value = body.get(name, _MISSING)
    if value is _MISSING:
        if required:
            bad(name, "is required")
        return default
    if value is None:
        if nullable:
            return None
        bad(name, "may not be null")
    return parse_iso(value, name)


COUNTRY_RE = r"^[A-Z]{2}$"
CURRENCY_RE = r"^[A-Z]{3}$"


def field_country(body, name, required=False, default=None, nullable=False):
    return field_str(body, name, required=required, default=default,
                     nullable=nullable, min_len=2, max_len=2, pattern=COUNTRY_RE)


def field_currency(body, name, required=False, default=None, nullable=False):
    return field_str(body, name, required=required, default=default,
                     nullable=nullable, min_len=3, max_len=3, pattern=CURRENCY_RE)


# --------------------------------------------------------------------------
# Query string helpers
# --------------------------------------------------------------------------
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = PAGE_DEFAULT_LIMIT
    else:
        limit_value = _query_int("limit", limit)
        if limit_value < PAGE_MIN_LIMIT or limit_value > PAGE_MAX_LIMIT:
            bad("limit", "must be between %d and %d" % (PAGE_MIN_LIMIT, PAGE_MAX_LIMIT))
    if offset is None or offset == "":
        offset_value = PAGE_DEFAULT_OFFSET
    else:
        offset_value = _query_int("offset", offset)
        if offset_value < 0:
            bad("offset", "must be non-negative")
    return limit_value, offset_value


def _query_int(name, raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        bad(name, "must be an integer")


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad(name, "must be true or false")


def query_required(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        bad(name, "is required")
    return raw


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
