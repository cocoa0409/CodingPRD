"""Authentication, role authorisation and request well-formedness helpers.

Implements gauntlet steps 1-3 of PRD sec 2.6:
  1. header authentication  -> ERR_UNAUTHENTICATED
  2. role authorisation     -> ERR_ROLE_NOT_PERMITTED
  3. request well-formedness -> ERR_INVALID_REQUEST
"""

import functools
from decimal import Decimal, InvalidOperation

from flask import g, request

import db
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_STATE_AGENCY_REVIEWER = "StateAgencyReviewer"
ROLE_SPONSOR_ADMIN = "SponsorAdmin"
ROLE_SITE_SUPERVISOR = "SiteSupervisor"
ROLE_FIELD_MONITOR = "FieldMonitor"

ALL_ROLES = (
    ROLE_STATE_AGENCY_REVIEWER,
    ROLE_SPONSOR_ADMIN,
    ROLE_SITE_SUPERVISOR,
    ROLE_FIELD_MONITOR,
)


def bad_request(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def acting_user_id():
    """The authenticated X-User-ID of the current request."""
    return getattr(g, "user_id", None)


def acting_role():
    return getattr(g, "user_role", None)


def endpoint(roles):
    """Decorator applying header authentication then role authorisation."""

    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get(USER_ID_HEADER)
            user_role = request.headers.get(USER_ROLE_HEADER)
            if not user_id or not user_role or user_role not in ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if user_role not in allowed:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")
            g.user_id = user_id
            g.user_role = user_role
            return view(*args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# Body access
# --------------------------------------------------------------------------
def json_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    body = request.get_json(force=True, silent=True)
    if body is None:
        bad_request("Request body must be valid JSON.")
    if not isinstance(body, dict):
        bad_request("Request body must be a JSON object.")
    return body


# --------------------------------------------------------------------------
# Scalar coercion / validation
# --------------------------------------------------------------------------
def _present(body, name, required):
    if name not in body or body[name] is None:
        if required:
            bad_request("Field '%s' is required." % name)
        return False
    return True


def field_str(body, name, required=True, default=None, allow_empty=False):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        bad_request("Field '%s' must not be empty." % name)
    return value


def field_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad_request(
            "Field '%s' must be one of: %s." % (name, ", ".join(sorted(allowed)))
        )
    return value


def field_int(body, name, required=True, default=None, minimum=0, maximum=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad_request("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad_request("Field '%s' must not exceed %d." % (name, maximum))
    return value


def field_bool(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad_request("Field '%s' must be a boolean." % name)
    return value


def field_decimal(
    body, name, required=True, default=None, minimum=None, maximum=None, places=None
):
    if not _present(body, name, required):
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad_request("Field '%s' must be a number." % name)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad_request("Field '%s' must be a number." % name)
    if number != number or number.is_infinite():  # NaN / inf guard
        bad_request("Field '%s' must be a finite number." % name)
    if minimum is not None and number < Decimal(str(minimum)):
        bad_request("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and number > Decimal(str(maximum)):
        bad_request("Field '%s' must not exceed %s." % (name, maximum))
    if places is not None and -number.as_tuple().exponent > places:
        bad_request("Field '%s' allows at most %d decimal places." % (name, places))
    return number


def field_date(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    parsed = db.parse_date(body[name])
    if parsed is None:
        bad_request("Field '%s' must be a calendar date written as YYYY-MM-DD." % name)
    return parsed


def field_time(body, name, required=True, default=None):
    """Returns minutes past midnight for an HH:MM 24-hour clock time."""
    if not _present(body, name, required):
        return default
    parsed = db.parse_hhmm(body[name])
    if parsed is None:
        bad_request("Field '%s' must be a clock time written as HH:MM." % name)
    return parsed


def field_datetime(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    parsed = db.parse_datetime(body[name])
    if parsed is None:
        bad_request("Field '%s' must be an ISO 8601 timestamp." % name)
    return parsed


def field_month(body, name, months=None, required=True, default=None):
    """A 'YYYY-MM' value, optionally restricted to a set of month numbers."""
    if not _present(body, name, required):
        return default
    value = body[name]
    parsed = db.parse_year_month(value)
    if parsed is None:
        bad_request("Field '%s' must be written as YYYY-MM." % name)
    if months is not None and parsed[1] not in months:
        bad_request("Field '%s' must name one of the program months." % name)
    return value


def field_list(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, list):
        bad_request("Field '%s' must be an array." % name)
    return value


def field_object(body, name, required=True, default=None):
    if not _present(body, name, required):
        return default
    value = body[name]
    if not isinstance(value, dict):
        bad_request("Field '%s' must be an object." % name)
    return value


# --------------------------------------------------------------------------
# Query parameters
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad_request("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad_request("Query parameter 'offset' must be at least 0.")
    return limit, offset


def query_value(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad_request(
            "Query parameter '%s' must be one of: %s." % (name, ", ".join(sorted(allowed)))
        )
    return value


def query_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        bad_request("Query parameter '%s' must be an integer." % name)


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = str(value).strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad_request("Query parameter '%s' must be a boolean." % name)


def query_date(name):
    value = request.args.get(name)
    if value is None:
        return None
    parsed = db.parse_date(value)
    if parsed is None:
        bad_request("Query parameter '%s' must be a date written as YYYY-MM-DD." % name)
    return parsed


def query_month(name):
    value = request.args.get(name)
    if value is None:
        return None
    if db.parse_year_month(value) is None:
        bad_request("Query parameter '%s' must be written as YYYY-MM." % name)
    return value
