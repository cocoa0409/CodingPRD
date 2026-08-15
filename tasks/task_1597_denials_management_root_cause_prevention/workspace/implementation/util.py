"""Shared helpers: logical-clock access, date/datetime parsing, and
request-body field validation (all schema failures -> ERR_VALIDATION 400).
"""

from datetime import date, datetime, timezone

from flask import request

from db import store
from errors import ApiError, ERR_VALIDATION

# ---------------------------------------------------------------------------
# Domain vocabularies
# ---------------------------------------------------------------------------

ROLES = (
    "DenialsSpecialist",
    "DenialsManager",
    "RevenueCycleDirector",
    "UpstreamOwner",
    "ComplianceAuditor",
)
ALL_ROLES = list(ROLES)

PLAN_TYPES = ("COMMERCIAL", "MEDICARE", "MEDICAID", "MANAGED_CARE")
CATEGORIES = (
    "REGISTRATION",
    "AUTHORIZATION",
    "CODING",
    "CLINICAL_DOCUMENTATION",
    "BILLING",
    "CONTRACTUAL",
)
DEPARTMENTS = ("REGISTRATION", "AUTHORIZATION", "CODING")
ATTACHMENT_TYPES = (
    "CLINICAL_NOTES",
    "PHYSICIAN_LETTER",
    "LAB_RESULTS",
    "AUTH_RECORD",
    "ITEMIZED_BILL",
    "REMITTANCE_COPY",
)
TASK_TYPES = ("PROCESS_FIX", "TRAINING", "SYSTEM_CONFIG", "DATA_QUALITY")
REASON_CODES = (
    "TIMELY_FILING_EXPIRED",
    "SMALL_BALANCE",
    "APPEALS_EXHAUSTED",
    "CONTRACTUAL_ADJUSTMENT",
    "OTHER",
)
OUTCOMES = ("OVERTURNED", "PARTIALLY_OVERTURNED", "UPHELD")
PAYER_STATUSES = ("ACTIVE", "INACTIVE")

# ---------------------------------------------------------------------------
# Logical clock helpers
# ---------------------------------------------------------------------------


def now_iso():
    """Current logical-clock timestamp, ISO 8601 UTC with 3 fractional digits."""
    dt = store.clock
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % ms


def today():
    """Current logical-clock calendar date."""
    return store.clock.date()


def parse_date(value, field="date"):
    """Parse a strict ISO calendar date (YYYY-MM-DD)."""
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, 400, "%s must be an ISO date string" % field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(ERR_VALIDATION, 400, "%s must be an ISO date (YYYY-MM-DD)" % field)


def parse_datetime(value, field="to_iso8601"):
    """Parse an ISO 8601 datetime (a trailing 'Z' or offset is accepted).
    Naive values are interpreted as UTC. Returns an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, 400, "%s must be an ISO 8601 timestamp" % field)
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise ApiError(ERR_VALIDATION, 400, "%s must be an ISO 8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_clock(dt):
    """Normalize an aware UTC datetime for the clock-control echo."""
    if dt.microsecond:
        ms = dt.microsecond // 1000
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % ms
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Request body validation helpers (PRD section 2.8 gate 3)
# ---------------------------------------------------------------------------


def get_body():
    """Return the JSON request body as a dict; an absent body counts as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def req_value(body, name):
    if not _present(body, name):
        raise ApiError(ERR_VALIDATION, 400, "Missing required field: %s" % name)
    return body[name]


def req_str(body, name):
    v = req_value(body, name)
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, "%s must be a string" % name)
    return v


def opt_str(body, name, default=None):
    if not _present(body, name):
        return default
    return req_str(body, name)


def req_int(body, name):
    v = req_value(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, 400, "%s must be an integer" % name)
    return v


def opt_int(body, name, default=None):
    if not _present(body, name):
        return default
    return req_int(body, name)


def req_bool(body, name):
    v = req_value(body, name)
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, 400, "%s must be a boolean" % name)
    return v


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    return req_bool(body, name)


def req_number(body, name):
    """A JSON number (int or float; booleans excluded)."""
    v = req_value(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_VALIDATION, 400, "%s must be a number" % name)
    return v


def req_enum(body, name, allowed):
    v = req_value(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            ERR_VALIDATION, 400, "%s must be one of %s" % (name, ", ".join(allowed))
        )
    return v


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_date(body, name):
    v = req_value(body, name)
    parse_date(v, name)
    return v


def opt_date(body, name, default=None):
    if not _present(body, name):
        return default
    return req_date(body, name)


def req_enum_list(body, name, allowed):
    v = req_value(body, name)
    if not isinstance(v, list):
        raise ApiError(ERR_VALIDATION, 400, "%s must be an array" % name)
    out = []
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            raise ApiError(
                ERR_VALIDATION, 400, "%s entries must be one of %s" % (name, ", ".join(allowed))
            )
        out.append(item)
    return out


def opt_enum_list(body, name, allowed, default=None):
    if not _present(body, name):
        return list(default) if default is not None else None
    return req_enum_list(body, name, allowed)


def sort_created(records):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
