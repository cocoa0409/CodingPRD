"""Authentication, authorisation, request-shape and existence guards.

Validation order is fixed system-wide by PRD Section 2.13; every route composes
these helpers in that order.
"""

import re
from datetime import datetime, timezone

from flask import request

from envelope import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import ApiError, fail
from store import db

ROLES = ("PlanAdministrator", "ComplianceExaminer", "ServicingCarrier", "ProducerAgent")

TERRITORIES = ("T01", "T02", "T03")

VIOLATION_CODES = (
    "SPEEDING_MINOR",
    "SPEEDING_MAJOR",
    "AT_FAULT_ACCIDENT",
    "LICENSE_SUSPENSION",
    "RECKLESS_DRIVING",
    "DUI",
)

DRIVER_CLASSES = ("ADULT", "YOUTHFUL_OPERATOR", "SENIOR")
VEHICLE_CLASSES = ("PLEASURE", "WORK_LT10", "WORK_GE10", "BUSINESS")

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"(?:[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?)?$"
)


# --------------------------------------------------------------------------
# 1 + 2: authentication and authorisation
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or unrecognised authentication headers.")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    return user_id, role


# --------------------------------------------------------------------------
# 3: request shape
# --------------------------------------------------------------------------
def invalid(msg="Request shape is invalid."):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        invalid("Body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        invalid("Body must be a JSON object.")
    return payload


def _present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, min_len=1, max_len=None, exact_len=None, pattern=None):
    if not _present(data, name):
        invalid("Field %s is required." % name)
    value = data[name]
    if not isinstance(value, str):
        invalid("Field %s must be a string." % name)
    if exact_len is not None and len(value) != exact_len:
        invalid("Field %s must be exactly %d characters." % (name, exact_len))
    if min_len is not None and len(value) < min_len:
        invalid("Field %s is too short." % name)
    if max_len is not None and len(value) > max_len:
        invalid("Field %s is too long." % name)
    if pattern is not None and not re.match(pattern, value):
        invalid("Field %s is malformed." % name)
    return value


def opt_str(data, name, default=None, min_len=1, max_len=None):
    if not _present(data, name):
        return default
    return req_str(data, name, min_len=min_len, max_len=max_len)


def req_enum(data, name, allowed):
    if not _present(data, name):
        invalid("Field %s is required." % name)
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        invalid("Field %s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    return req_enum(data, name, allowed)


def req_int(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        invalid("Field %s is required." % name)
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field %s must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid("Field %s is below the accepted minimum." % name)
    if maximum is not None and value > maximum:
        invalid("Field %s is above the accepted maximum." % name)
    return value


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def req_bool(data, name):
    if not _present(data, name):
        invalid("Field %s is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        invalid("Field %s must be a boolean." % name)
    return value


def parse_iso(value, name):
    if not isinstance(value, str) or not _ISO_RE.match(value):
        invalid("Field %s must be an ISO 8601 UTC timestamp." % name)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        invalid("Field %s must be an ISO 8601 UTC timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_dt(data, name):
    if not _present(data, name):
        invalid("Field %s is required." % name)
    return parse_iso(data[name], name)


def opt_dt(data, name, default=None):
    if not _present(data, name):
        return default
    return parse_iso(data[name], name)


def req_territories(data, name, allow_empty=False, unique=True):
    if not _present(data, name):
        invalid("Field %s is required." % name)
    value = data[name]
    if not isinstance(value, list):
        invalid("Field %s must be an array." % name)
    if not value and not allow_empty:
        invalid("Field %s must not be empty." % name)
    for element in value:
        if not isinstance(element, str) or element not in TERRITORIES:
            invalid("Field %s contains an unknown territory code." % name)
    if unique and len(set(value)) != len(value):
        invalid("Field %s must not contain duplicates." % name)
    return list(value)


def opt_territories(data, name, default=None, allow_empty=True, unique=False):
    if not _present(data, name):
        return list(default) if default is not None else []
    return req_territories(data, name, allow_empty=allow_empty, unique=unique)


def req_violations(data, name):
    if not _present(data, name):
        invalid("Field %s is required." % name)
    return _parse_violations(data[name], name)


def opt_violations(data, name, default=None):
    if not _present(data, name):
        return default
    return _parse_violations(data[name], name)


def _parse_violations(value, name):
    if not isinstance(value, list):
        invalid("Field %s must be an array." % name)
    out = []
    for element in value:
        if not isinstance(element, dict):
            invalid("Field %s elements must be objects." % name)
        code = req_enum(element, "code", VIOLATION_CODES)
        conviction_date = req_dt(element, "conviction_date")
        out.append({"code": code, "conviction_date": conviction_date})
    return out


def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            invalid("Query parameter limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            invalid("Query parameter limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            invalid("Query parameter offset must be an integer.")
        if offset < 0:
            invalid("Query parameter offset must not be negative.")
    return limit, offset


# --------------------------------------------------------------------------
# 4: existence
# --------------------------------------------------------------------------
def _lookup(table, row_id, error_id):
    if not isinstance(row_id, str) or row_id not in table:
        fail(error_id)
    return table[row_id]


def need_carrier(row_id):
    return _lookup(db.carriers, row_id, "ERR_CARRIER_NOT_FOUND")


def need_producer(row_id):
    return _lookup(db.producers, row_id, "ERR_PRODUCER_NOT_FOUND")


def need_applicant(row_id):
    return _lookup(db.applicants, row_id, "ERR_APPLICANT_NOT_FOUND")


def need_vehicle(row_id):
    return _lookup(db.vehicles, row_id, "ERR_VEHICLE_NOT_FOUND")


def need_application(row_id):
    return _lookup(db.applications, row_id, "ERR_APPLICATION_NOT_FOUND")


def need_plan_period(row_id):
    return _lookup(db.plan_periods, row_id, "ERR_PLAN_PERIOD_NOT_FOUND")


def need_cycle(row_id):
    return _lookup(db.assignment_cycles, row_id, "ERR_ASSIGNMENT_CYCLE_NOT_FOUND")


def need_assignment(row_id):
    return _lookup(db.assignments, row_id, "ERR_ASSIGNMENT_NOT_FOUND")


def need_policy(row_id):
    return _lookup(db.policies, row_id, "ERR_POLICY_NOT_FOUND")


def need_claim(row_id):
    return _lookup(db.claims, row_id, "ERR_CLAIM_NOT_FOUND")


def need_complaint(row_id):
    return _lookup(db.complaints, row_id, "ERR_COMPLAINT_NOT_FOUND")


def need_reconciliation(row_id):
    return _lookup(db.reconciliations, row_id, "ERR_QUOTA_RECONCILIATION_NOT_FOUND")


# --------------------------------------------------------------------------
# 5: ownership scope
# --------------------------------------------------------------------------
def carrier_scope(role, user_id, carrier_id):
    if role == "ServicingCarrier" and carrier_id != user_id:
        fail("ERR_CARRIER_SCOPE_FORBIDDEN")


def producer_scope(role, user_id, producer_id):
    if role == "ProducerAgent" and producer_id != user_id:
        fail("ERR_PRODUCER_SCOPE_FORBIDDEN")
