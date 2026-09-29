"""Request-shape validation (ladder stages 5-9) and lookup helpers."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import ApiError

# ---------------------------------------------------------------- enumerations
INDUSTRY_CODES = ("FINANCIAL_SERVICES", "MANUFACTURING", "GOVERNMENT", "TECHNOLOGY", "HEALTHCARE")
LEVELS = ("STAFF", "SENIOR", "MANAGER", "PARTNER")
SERVICE_CENTERS = ("DOMESTIC", "OFFSHORE")
SERVICE_LINES = ("AUDIT", "TAX", "ADVISORY")
PHASE_TYPES = ("PLANNING", "INTERIM", "FIELDWORK", "REVIEW", "WRAP_UP")
EXCEPTION_TYPES = ("PTO", "LICENSURE_STUDY_LEAVE", "TRAINING", "FIRM_HOLIDAY")
ENTRY_TYPES = ("EXECUTION", "REVIEW", "REWORK")
RESTRICTION_TYPES = (
    "FINANCIAL_INTEREST",
    "EMPLOYMENT_NEGOTIATION",
    "ROTATION_COOLING_OFF",
    "RELATIVE_EMPLOYED",
)
TRIGGER_REASONS = ("CLIENT_READINESS_SLIP", "SCOPE_EXPANSION", "STAFF_ATTRITION")
ENGAGEMENT_STATUSES = ("SETUP", "SCHEDULED", "IN_FIELDWORK", "CLIENT_BLOCKED", "DELIVERED")
RISK_BANDS = ("LOW", "MEDIUM", "HIGH")
TURNOVER_BANDS = ("LOW", "ELEVATED", "HIGH")
PHASE_STATUSES = (
    "NOT_STAFFED",
    "PARTIALLY_STAFFED",
    "FULLY_STAFFED",
    "IN_PROGRESS",
    "COMPLETE",
)
STAFFING_STATUSES = ("PROPOSED", "CONFIRMED", "ACTIVE", "COMPLETED", "RELEASED")
REVIEW_STATUSES = (
    "NOT_REQUIRED",
    "PENDING_REVIEW",
    "IN_REVIEW",
    "REWORK_REQUESTED",
    "REVIEW_ACCEPTED",
)
PLAN_STATUSES = ("DRAFT", "SIMULATED", "APPLIED", "SUPERSEDED")
WAIVER_STATUSES = ("REQUESTED", "APPROVED", "DENIED", "EXPIRED")


def bad(field, why="is invalid"):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


# ------------------------------------------------------------------ body access
def json_body():
    body = request.get_json(silent=True)
    if body is None:
        if not request.get_data():
            return {}
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


# ------------------------------------------------------------- field extractors
def _present(body, field):
    return field in body and body[field] is not None


def req_string(body, field, min_len=1, max_len=None):
    if not _present(body, field):
        bad(field, "is required")
    value = body[field]
    if not isinstance(value, str):
        bad(field, "must be a string")
    if len(value) < min_len:
        bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        bad(field, "must be at most %d characters" % max_len)
    return value


def opt_string(body, field, min_len=0, max_len=None, default=None):
    if not _present(body, field):
        return default
    return req_string(body, field, min_len, max_len)


def req_enum(body, field, allowed):
    value = req_string(body, field)
    if value not in allowed:
        bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(body, field, allowed, default=None):
    if not _present(body, field):
        return default
    return req_enum(body, field, allowed)


def _to_decimal(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad(field, "must be a number")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad(field, "must be a number")


def req_number(body, field, minimum=None, maximum=None, exclusive_min=False):
    if not _present(body, field):
        bad(field, "is required")
    value = _to_decimal(field, body[field])
    _range_check(field, value, minimum, maximum, exclusive_min)
    return value


def opt_number(body, field, minimum=None, maximum=None, exclusive_min=False, default=None):
    if not _present(body, field):
        return default
    return req_number(body, field, minimum, maximum, exclusive_min)


def _range_check(field, value, minimum, maximum, exclusive_min):
    if minimum is not None:
        if exclusive_min and value <= minimum:
            bad(field, "must be strictly greater than %s" % minimum)
        if not exclusive_min and value < minimum:
            bad(field, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be at most %s" % maximum)


def req_integer(body, field, minimum=None, maximum=None):
    if not _present(body, field):
        bad(field, "is required")
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        bad(field, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be at most %d" % maximum)
    return value


def req_boolean(body, field):
    if not _present(body, field):
        bad(field, "is required")
    if not isinstance(body[field], bool):
        bad(field, "must be a boolean")
    return body[field]


def opt_boolean(body, field, default=False):
    if not _present(body, field):
        return default
    return req_boolean(body, field)


def parse_iso_date(field, value):
    if not isinstance(value, str):
        bad(field, "must be an ISO date string (YYYY-MM-DD)")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        bad(field, "must be an ISO date string (YYYY-MM-DD)")
    return parsed


def req_date(body, field):
    if not _present(body, field):
        bad(field, "is required")
    return parse_iso_date(field, body[field])


def opt_date(body, field, default=None):
    if not _present(body, field):
        return default
    return req_date(body, field)


def req_instant(body, field):
    """Parse an ISO 8601 instant such as 2026-08-01T00:00:00Z."""
    raw = req_string(body, field)
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad(field, "must be an ISO 8601 instant")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ------------------------------------------------------------------- pagination
def pagination():
    """Ladder stage 7."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        limit = _positive_int(limit_raw)
        if limit is None or limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if offset_raw is not None:
        offset = _positive_int(offset_raw)
        if offset is None or offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def _positive_int(raw):
    text = raw.strip()
    if not text:
        return None
    sign = 1
    if text[0] in "+-":
        if text[0] == "-":
            sign = -1
        text = text[1:]
    if not text.isdigit():
        return None
    return sign * int(text)


# --------------------------------------------------------------- week semantics
def require_monday(field, value):
    """Ladder stage 9."""
    if value.weekday() != 0:
        raise ApiError("ERR_NOT_WEEK_START", "%s must be a Monday." % field)
    return value


# ------------------------------------------------------------- entity resolution
def _lookup(table, identifier, error_id):
    if not isinstance(identifier, str):
        return None
    return table.get(identifier)


def path_client(client_id):
    row = _lookup(db.clients, client_id, "ERR_CLIENT_NOT_FOUND")
    if row is None:
        raise ApiError("ERR_CLIENT_NOT_FOUND", "Client '%s' does not exist." % client_id)
    return row


def path_staff(staff_id):
    row = _lookup(db.staff_members, staff_id, "ERR_STAFF_MEMBER_NOT_FOUND")
    if row is None:
        raise ApiError("ERR_STAFF_MEMBER_NOT_FOUND", "Staff member '%s' does not exist." % staff_id)
    return row


def path_engagement(engagement_id):
    row = _lookup(db.engagements, engagement_id, "ERR_ENGAGEMENT_NOT_FOUND")
    if row is None:
        raise ApiError("ERR_ENGAGEMENT_NOT_FOUND", "Engagement '%s' does not exist." % engagement_id)
    return row


def path_phase(phase_id):
    row = _lookup(db.phases, phase_id, "ERR_PHASE_NOT_FOUND")
    if row is None:
        raise ApiError("ERR_PHASE_NOT_FOUND", "Engagement phase '%s' does not exist." % phase_id)
    return row


def path_assignment(assignment_id):
    row = _lookup(db.assignments, assignment_id, "ERR_ASSIGNMENT_NOT_FOUND")
    if row is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND", "Assignment '%s' does not exist." % assignment_id)
    return row


def path_restriction(restriction_id):
    row = _lookup(db.restrictions, restriction_id, "ERR_RESTRICTION_NOT_FOUND")
    if row is None:
        raise ApiError(
            "ERR_RESTRICTION_NOT_FOUND", "Independence restriction '%s' does not exist." % restriction_id
        )
    return row


def path_review_window(window_id):
    row = _lookup(db.review_windows, window_id, "ERR_REVIEW_WINDOW_NOT_FOUND")
    if row is None:
        raise ApiError(
            "ERR_REVIEW_WINDOW_NOT_FOUND", "Review capacity window '%s' does not exist." % window_id
        )
    return row


def path_plan(plan_id):
    row = _lookup(db.reschedule_plans, plan_id, "ERR_RESCHEDULE_PLAN_NOT_FOUND")
    if row is None:
        raise ApiError("ERR_RESCHEDULE_PLAN_NOT_FOUND", "Reschedule plan '%s' does not exist." % plan_id)
    return row


def path_waiver(waiver_id):
    row = _lookup(db.waivers, waiver_id, "ERR_WAIVER_NOT_FOUND")
    if row is None:
        raise ApiError("ERR_WAIVER_NOT_FOUND", "Workload waiver '%s' does not exist." % waiver_id)
    return row


def body_fk(body, field, table, error_id):
    """Ladder stage 5: resolve a body foreign key when it is a string.

    An absent or non-string value is left for stage 6 (ERR_INVALID_REQUEST).
    """
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if not isinstance(value, str):
        return None
    row = table.get(value)
    if row is None:
        raise ApiError(error_id, "Referenced '%s' (%s) does not exist." % (field, value))
    return row
