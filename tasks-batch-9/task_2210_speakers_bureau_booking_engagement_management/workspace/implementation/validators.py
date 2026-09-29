"""Body well-formedness (ladder band 4) and query-parameter validation."""

from flask import request

import errors
from errors import fail
from timeutil import parse_iso

# --- enumerations -----------------------------------------------------------
TOPIC_CODES = (
    "AI_STRATEGY",
    "LEADERSHIP",
    "HEALTHCARE_POLICY",
    "CYBERSECURITY",
    "FUTURE_OF_WORK",
    "SALES_MOTIVATION",
)
TRAVEL_CLASSES = ("ECONOMY", "PREMIUM", "BUSINESS")
ROSTER_STATUSES = ("ACTIVE", "PROBATION", "PAUSED", "RETIRED")
TAX_FORM_STATUSES = ("MISSING", "ON_FILE")
ROSTER_TIERS = ("BRONZE", "SILVER", "GOLD")
INDUSTRY_CODES = ("HEALTHCARE", "FINANCE", "TECHNOLOGY", "EDUCATION", "MANUFACTURING")
CREDIT_STATUSES = ("GOOD", "WATCH", "HOLD")
OBJECTIVE_TAGS = ("INSPIRE", "STRATEGY", "TRAINING", "CELEBRATE")
INQUIRY_STATUSES = (
    "RECEIVED",
    "QUALIFIED",
    "BLOCKED",
    "PROPOSED",
    "WON",
    "LOST",
    "DISQUALIFIED",
)
PROPOSAL_STATUSES = (
    "DRAFT",
    "PRESENTED",
    "REVISION_REQUESTED",
    "ACCEPTED",
    "DECLINED",
    "SUPERSEDED",
    "CLOSED",
)
OPTION_STATUSES = ("OFFERED", "SELECTED", "REJECTED", "WITHDRAWN")
BOOKING_STATUSES = (
    "OFFERED",
    "CONFIRMED",
    "CONTRACTED",
    "DELIVERED",
    "DECLINED_BY_SPEAKER",
    "CANCELLED_BY_CLIENT",
    "CANCELLED_BY_SPEAKER",
)
SETTLEMENT_STATUSES = (
    "UNBILLED",
    "INVOICED",
    "PARTIALLY_COLLECTED",
    "COLLECTED",
    "REMITTED",
    "WAIVED",
    "WRITTEN_OFF",
)
CONTRACT_STATUSES = ("DRAFT", "SENT", "PARTIALLY_SIGNED", "EXECUTED", "VOID")
CANCELLATION_SCHEDULES = ("STANDARD", "STRICT")
TRAVEL_POLICIES = ("POLICY_A", "POLICY_B")
RECORDING_RIGHTS = ("NONE", "AUDIO_ONLY", "FULL_BUY_OUT")
TECHNICAL_RIDERS = ("STANDARD_AV", "STAGE_PLUS", "BROADCAST")
EXCLUSIVITY_DAYS = (0, 30, 90, 180)
HOLD_KINDS = ("ENGAGEMENT", "BLACKOUT")
HOLD_STATUSES = ("ACTIVE", "RELEASED", "CONSUMED")
GRANT_STATUSES = ("ACTIVE", "EXPIRED", "WAIVED")
DISTANCE_BANDS = ("LOCAL", "REGIONAL", "NATIONAL", "INTERNATIONAL")
EXPENSE_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "REIMBURSED")
INVOICE_KINDS = ("ENGAGEMENT_FEE", "CANCELLATION_RETENTION")
INVOICE_STATUSES = ("ISSUED", "PARTIALLY_PAID", "PAID", "VOID")
REMITTANCE_STATUSES = ("PENDING", "APPROVED", "PAID", "VOIDED")
CLAIM_STATUSES = ("OPEN", "UPHELD", "DISMISSED", "SETTLED")
CANCELLED_BY = ("CLIENT", "SPEAKER", "BUREAU")
QUALIFY_OUTCOMES = ("QUALIFY", "DISQUALIFY")
RESOLVE_OUTCOMES = ("UPHOLD", "DISMISS", "SETTLE")
PERFORMANCE_VARIANTS = ("ROLLING", "LIFETIME")


def _bad(message):
    fail(errors.ERR_INVALID_REQUEST, message)


def body():
    """Parse the JSON body.  A malformed body is ERR_INVALID_REQUEST."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        _bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object.")
    return parsed


def _present(data, key):
    return key in data and data[key] is not None


def req_string(data, key, min_len=1, max_len=None):
    if not _present(data, key):
        _bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % key)
    if len(value) < min_len:
        _bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def opt_string(data, key, default=None, max_len=None):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % key)
    if max_len is not None and len(value) > max_len:
        _bad("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        _bad("Field '%s' is required." % key)
    value = data[key]
    if not _is_int(value):
        _bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be <= %s." % (key, maximum))
    return value


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if not _present(data, key):
        return default
    return req_int(data, key, minimum, maximum)


def req_cents(data, key):
    return req_int(data, key, minimum=0)


def opt_cents(data, key, default=0):
    if not _present(data, key):
        return default
    return req_int(data, key, minimum=0)


def req_number(data, key):
    if not _present(data, key):
        _bad("Field '%s' is required." % key)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number." % key)
    return value


def req_bool(data, key):
    if not _present(data, key):
        _bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % key)
    return value


def opt_bool(data, key, default=False):
    if not _present(data, key):
        return default
    return req_bool(data, key)


def req_enum(data, key, allowed):
    if not _present(data, key):
        _bad("Field '%s' is required." % key)
    value = data[key]
    if value not in allowed:
        _bad("Field '%s' must be one of %s." % (key, ", ".join(map(str, allowed))))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def req_dt(data, key):
    """Returns (raw_string, datetime)."""
    if not _present(data, key):
        _bad("Field '%s' is required." % key)
    value = data[key]
    parsed = parse_iso(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 UTC instant." % key)
    return value, parsed


def req_code_list(data, key, allowed, min_items, max_items):
    if not _present(data, key):
        _bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % key)
    if len(value) < min_items or len(value) > max_items:
        _bad("Field '%s' must carry between %d and %d entries." % (key, min_items, max_items))
    for item in value:
        if item not in allowed:
            _bad("Field '%s' contains an undeclared code." % key)
    if len(set(value)) != len(value):
        _bad("Field '%s' entries must be distinct." % key)
    return list(value)


# --- query parameters -------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            _bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            _bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        _bad("Query parameter '%s' must be one of %s." % (name, ", ".join(map(str, allowed))))
    return value


def query_string(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        _bad("Query parameter '%s' must be an integer." % name)
