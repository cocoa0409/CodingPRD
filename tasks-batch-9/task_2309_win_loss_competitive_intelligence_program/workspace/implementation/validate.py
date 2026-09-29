"""Structural validation (precedence 7), pagination bounds and enum members."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from util import dec, parse_dt

# ---------------------------------------------------------------- enumerations
ROLES_ENUM = (
    "ProgramAdmin", "ResearchAnalyst", "LegalReviewer",
    "EnablementManager", "ProductManager", "SalesRep",
)
PROGRAM_STATUS = ("DRAFT", "ACTIVE", "CLOSING", "CLOSED")
POSTURE = ("OPEN", "RESTRICTED", "FROZEN")
INDEPENDENCE_MODE = ("STRICT", "ADVISORY")
QUESTION_KEYS = (
    "EVALUATION_CRITERIA", "COMPETITOR_POSITIONING", "PRICING_PERCEPTION",
    "LOSS_REASON", "PRODUCT_GAP",
)
REQUIRED_GUIDE_KEYS = (
    "EVALUATION_CRITERIA", "COMPETITOR_POSITIONING", "PRICING_PERCEPTION",
)
COMPETITOR_TIER = ("PRIMARY", "SECONDARY", "EMERGING")
COMPETITOR_STATUS = ("ACTIVE", "ARCHIVED")
OUTCOME = ("WON", "LOST", "NO_DECISION")
SEGMENT = ("ENTERPRISE", "MIDMARKET", "SMB")
RESEARCH_STATUS = ("NOT_SELECTED", "SELECTED", "DECLINED", "INTERVIEWED", "SYNTHESIZED")
ATTRIBUTION_STATUS = ("UNATTRIBUTED", "PROVISIONAL", "RATIFIED")
EMPLOYMENT_TYPE = ("INTERNAL", "EXTERNAL_VENDOR")
ANALYST_STATUS = ("ACTIVE", "INACTIVE")
TITLE_BAND = ("ECONOMIC_BUYER", "CHAMPION", "PROCUREMENT", "END_USER")
CONSENT_STATUS = ("NOT_REQUESTED", "REQUESTED", "GRANTED", "REFUSED")
CONSENT_INPUT = ("REQUESTED", "GRANTED", "REFUSED")
INCENTIVE_ELIGIBILITY = ("ELIGIBLE", "INELIGIBLE_PUBLIC_SECTOR", "INELIGIBLE_POLICY")
SELECTION_BASIS = ("STRATIFIED_BY_SEGMENT", "VALUE_WEIGHTED")
FRAME_STATUS = ("DRAFT", "SEALED", "SUSPENDED", "CLOSED")
INTERVIEW_STATUS = ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
INCENTIVE_STATUS = ("COMMITTED", "PAID", "RELEASED", "FORFEITED")
REASON_STATUS = ("ACTIVE", "DEPRECATED")
ATTR_STATUS = ("PROVISIONAL", "RATIFIED", "SUPERSEDED")
BATTLECARD_STATUS = ("DRAFT", "LEGAL_REVIEW", "APPROVED", "PUBLISHED", "WITHDRAWN")
CLAIM_TYPE = ("PRICING", "FEATURE", "PERFORMANCE", "REFERENCE")
SUBSTANTIATION_LEVEL = ("UNSUBSTANTIATED", "ANECDOTAL", "CORROBORATED")
RISK_CLASS = ("LOW", "MEDIUM", "HIGH")
LEGAL_STATUS = ("PENDING", "APPROVED", "CONDITIONAL", "REJECTED")
LEGAL_DECISION = ("APPROVE", "CONDITIONAL", "REJECT")
GAP_STATUS = ("NEW", "TRIAGED", "ACCEPTED", "DECLINED", "PROMOTED")
PRIORITY_BAND = ("P0", "P1", "P2", "P3")
TRIAGE_DECISION = ("ACCEPT", "NEEDS_EVIDENCE", "DECLINE")
ASSIGNMENT_STATUS = ("ASSIGNED", "FAILED", "TRAINED", "EXPIRED")
TREND_BASIS = ("RATIFIED_ONLY", "INCLUDE_PROVISIONAL")


# ------------------------------------------------------------------ body access
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def present(payload, field):
    return field in payload and payload[field] is not None


# ------------------------------------------------------------------- primitives
def req_str(payload, field, allow_empty=False):
    if field not in payload or payload[field] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = payload[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string." % field)
    return value


def opt_str(payload, field, allow_empty=False, default=None):
    if not present(payload, field):
        return default
    return req_str(payload, field, allow_empty)


def req_enum(payload, field, allowed):
    value = req_str(payload, field)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a declared enum member." % field)
    return value


def opt_enum(payload, field, allowed, default=None):
    if not present(payload, field):
        return default
    return req_enum(payload, field, allowed)


def _as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    try:
        return dec(value)
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)


def req_number(payload, field):
    if field not in payload or payload[field] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    return _as_number(payload[field], field)


def opt_number(payload, field, default=None):
    if not present(payload, field):
        return default
    return _as_number(payload[field], field)


def req_int(payload, field):
    if field not in payload or payload[field] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    return value


def opt_int(payload, field, default=None):
    if not present(payload, field):
        return default
    return req_int(payload, field)


def req_bool(payload, field):
    value = payload[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


def opt_bool(payload, field, default=None):
    if not present(payload, field):
        return default
    return req_bool(payload, field)


def req_dt(payload, field):
    value = req_str(payload, field)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a well-formed datetime." % field)
    return parsed


def opt_dt(payload, field, default=None):
    if not present(payload, field):
        return default
    return req_dt(payload, field)


def req_str_array(payload, field, non_empty=True):
    if field not in payload or payload[field] is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = payload[field]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % field)
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an array of strings." % field)
    if non_empty and len(value) == 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty array." % field)
    return value


def opt_str_array(payload, field, non_empty=False, default=None):
    if not present(payload, field):
        return default
    return req_str_array(payload, field, non_empty)


def req_enum_array(payload, field, allowed, non_empty=False):
    value = req_str_array(payload, field, non_empty)
    for item in value:
        if item not in allowed:
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' contains an undeclared enum member." % field)
    return value


# ------------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if str(raw).strip() != str(limit):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100 inclusive.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if str(raw).strip() != str(offset):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' is not a declared enum member." % name)
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def query_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    return parsed


def query_dt_required(name):
    value = request.args.get(name)
    if value is None or value == "":
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is required." % name)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' is not a well-formed datetime." % name)
    return parsed


# ------------------------------------------------------ existence resolution (5,6)
def resolve(table, key, error_id):
    """Resolve an identifier or raise the matching not-found error."""
    if key is None:
        return None
    row = table.get(key)
    if row is None:
        from errors import fail as _fail
        _fail(error_id)
    return row


def fk_from_body(payload, field, table, error_id):
    """Precedence 6: resolve a body foreign key that is present and a string.

    Absent / wrong-typed values are left for structural validation (precedence 7).
    """
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if not isinstance(value, str):
        return None
    row = table.get(value)
    if row is None:
        fail(error_id)
    return row


def fk_from_query(name, table, error_id):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    row = table.get(value)
    if row is None:
        fail(error_id)
    return value


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
