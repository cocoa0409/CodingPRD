"""Request-shape validation: the two-pass body parser, enum sets, pagination.

PRD 2.7 puts request shape (check 4, ERR_INVALID_REQUEST) strictly before
enumerated values (check 5, ERR_INVALID_ENUM_VALUE) and both before pagination
bounds (check 6, ERR_INVALID_PAGINATION).  The parser therefore runs presence /
type / range / date checks over EVERY declared field first, and only then walks
the same spec a second time for enum membership.
"""

from datetime import datetime, timezone

from flask import request

from errors import invalid_enum, invalid_pagination, invalid_request
from responses import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

# ------------------------------------------------------------------ enum sets
REGION_CODES = ["US-CA-SFO", "US-NY-NYC", "US-IL-CHI", "US-WA-SEA", "US-TX-AUS"]
CATEGORY_TYPES = ["TRANSIT_PASS", "VANPOOL", "PARKING"]
MEDIA_TYPES = ["PAPER_PASS", "SMART_CARD_LOAD", "DEBIT_CARD"]
PAYROLL_CYCLES = ["SEMI_MONTHLY", "MONTHLY"]
SPILL_POLICIES = ["SPILL_TO_POSTTAX", "REJECT_OVERAGE"]
ROLLOVER_POLICIES = ["NO_ROLLOVER", "CAP_ROLLOVER", "FULL_ROLLOVER"]
DOC_TYPES = ["RECEIPT", "FARE_STATEMENT", "PARKING_INVOICE", "EMPLOYER_ATTESTATION"]
REJECTION_REASONS = [
    "AMOUNT_MISMATCH",
    "INELIGIBLE_EXPENSE",
    "ILLEGIBLE_DOCUMENT",
    "LATE_SUBMISSION",
]
UNDELIVERED_REASONS = ["NEVER_ARRIVED", "LOST", "STOLEN", "DAMAGED"]
ACK_OUTCOMES = ["ACCEPTED", "REJECTED"]
ENTRY_TYPES = [
    "ROLLOVER_IN",
    "CONTRIBUTION",
    "CONTRIBUTION_ADJUSTMENT",
    "SPEND",
    "SPEND_REVERSAL",
    "FORFEITURE",
    "REFUND",
    "FUNDING_REVERSAL",
    "REPLACEMENT_FEE",
]
SOURCE_ENTITIES = ["BenefitAccount", "Election", "CardTransaction", "MediaOrder"]

PROGRAM_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED"]
ORDINANCE_STATUSES = ["UNASSESSED", "EXEMPT", "MANDATED_COMPLIANT", "MANDATED_NONCOMPLIANT"]
MANDATE_STATUSES = ["EXEMPT", "MANDATED_COMPLIANT", "MANDATED_NONCOMPLIANT"]
FINDINGS = [
    "COMPLIANT",
    "EXEMPT_REGION_NOT_COVERED",
    "EXEMPT_BELOW_THRESHOLD",
    "DEFICIENT_NO_QUALIFYING_TRANSIT_OFFERING",
    "DEFICIENT_LIMIT_BELOW_MINIMUM",
]
CATEGORY_STATUSES = ["ACTIVE", "RETIRED"]
EMPLOYEE_STATUSES = ["ACTIVE", "TERMINATED"]
WINDOW_STATUSES = ["SCHEDULED", "OPEN", "LOCKED", "CLOSED"]
FUNDING_STATUSES = ["PENDING", "HELD", "FUNDED", "REVERSED", "CANCELLED", "SETTLED"]
FULFILLMENT_STATUSES = [
    "NOT_REQUIRED",
    "AWAITING_ORDER",
    "ORDERED",
    "IN_TRANSIT",
    "DELIVERED",
    "REPLACEMENT_PENDING",
    "CANCELLED",
]
MEDIA_CATALOG_STATUSES = ["ACTIVE", "DISCONTINUED"]
BATCH_STATUSES = ["OPEN", "SEALED", "RELEASED", "RECONCILED"]
MEDIA_ORDER_STATUSES = [
    "PENDING",
    "SUBMITTED",
    "SHIPPED",
    "DELIVERED",
    "UNDELIVERED",
    "CANCELLED",
]
SUBSTANTIATION_STATUSES = [
    "AUTO_SUBSTANTIATED",
    "PENDING_DOCS",
    "SUBSTANTIATED",
    "INELIGIBLE",
]
CLAIM_STATUSES = ["SUBMITTED", "APPROVED", "REJECTED"]
PAYROLL_FILE_STATUSES = ["DRAFT", "GENERATED", "TRANSMITTED", "ACKNOWLEDGED", "REJECTED"]
LIMIT_GROUPS = ["TRANSIT", "PARKING"]
EXCLUSION_BASES = ["ELECTED_BASIS", "FUNDED_BASIS"]

_SENTINEL = object()


# ------------------------------------------------------------- scalar parsing
def parse_iso8601(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_month(value):
    """Validate an exact YYYY-MM month string; return (year, month) or None."""
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        return None
    year_part, month_part = value[:4], value[5:]
    if not (year_part.isdigit() and month_part.isdigit()):
        return None
    month = int(month_part)
    if month < 1 or month > 12:
        return None
    return int(year_part), month


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


# --------------------------------------------------------------- body parsing
def raw_body():
    """The JSON body as a dict; a missing body is treated as empty."""
    body = request.get_json(silent=True)
    if body is None:
        if request.data and request.data.strip():
            invalid_request("Request body must be a JSON object.")
        return {}
    if not isinstance(body, dict):
        invalid_request("Request body must be a JSON object.")
    return body


def field(name, ftype, required=False, default=_SENTINEL, minimum=None, maximum=None,
          min_len=None, max_len=None, choices=None, nullable=False):
    return {
        "name": name,
        "type": ftype,
        "required": required,
        "default": default,
        "minimum": minimum,
        "maximum": maximum,
        "min_len": min_len,
        "max_len": max_len,
        "choices": choices,
        "nullable": nullable,
    }


def _shape_check(spec, body, out):
    """Pass 1: presence, JSON type, numeric range, string length, date / month shape."""
    name = spec["name"]
    if name not in body:
        if spec["required"]:
            invalid_request("Field '%s' is required." % name)
        if spec["default"] is not _SENTINEL:
            out[name] = spec["default"]
        return
    value = body[name]
    if value is None:
        if spec["nullable"]:
            out[name] = None
            return
        invalid_request("Field '%s' must not be null." % name)
    ftype = spec["type"]
    if ftype == "integer":
        if not is_int(value):
            invalid_request("Field '%s' must be an integer." % name)
        if spec["minimum"] is not None and value < spec["minimum"]:
            invalid_request(
                "Field '%s' must be >= %d." % (name, spec["minimum"]))
        if spec["maximum"] is not None and value > spec["maximum"]:
            invalid_request(
                "Field '%s' must be <= %d." % (name, spec["maximum"]))
        out[name] = value
    elif ftype == "boolean":
        if not isinstance(value, bool):
            invalid_request("Field '%s' must be a boolean." % name)
        out[name] = value
    elif ftype in ("string", "enum", "id"):
        if not isinstance(value, str):
            invalid_request("Field '%s' must be a string." % name)
        if spec["min_len"] is not None and len(value) < spec["min_len"]:
            invalid_request(
                "Field '%s' must be at least %d characters." % (name, spec["min_len"]))
        if spec["max_len"] is not None and len(value) > spec["max_len"]:
            invalid_request(
                "Field '%s' must be at most %d characters." % (name, spec["max_len"]))
        if ftype == "string" and spec["min_len"] and not value.strip():
            invalid_request("Field '%s' must not be blank." % name)
        out[name] = value
    elif ftype == "datetime":
        if not isinstance(value, str):
            invalid_request("Field '%s' must be an ISO 8601 string." % name)
        parsed = parse_iso8601(value)
        if parsed is None:
            invalid_request("Field '%s' must be a valid ISO 8601 instant." % name)
        out[name] = parsed
    elif ftype == "month":
        if not isinstance(value, str):
            invalid_request("Field '%s' must be a YYYY-MM string." % name)
        if parse_month(value) is None:
            invalid_request("Field '%s' must match exactly YYYY-MM." % name)
        out[name] = value
    else:  # pragma: no cover - defensive
        out[name] = value


def _enum_check(spec, body):
    """Pass 2: enum membership, run only after every shape check has passed."""
    if spec["type"] != "enum" or spec["choices"] is None:
        return
    name = spec["name"]
    if name not in body or body[name] is None:
        return
    if body[name] not in spec["choices"]:
        invalid_enum("Field '%s' must be one of: %s." % (name, ", ".join(spec["choices"])))


def parse_body(specs):
    """Run the two passes and return the parsed values (defaults applied)."""
    body = raw_body()
    out = {}
    for spec in specs:
        _shape_check(spec, body, out)
    for spec in specs:
        _enum_check(spec, body)
    return body, out


# ----------------------------------------------------------------- query args
def _query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        invalid_pagination("Query parameter '%s' must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        invalid_pagination("Query parameter '%s' must be an integer." % name)
    return -int(digits) if negative else int(digits)


def pagination():
    """Resolve limit / offset. Must be called AFTER enum query filters are checked."""
    limit = _query_int("limit")
    offset = _query_int("offset")
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    elif limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        invalid_pagination(
            "Query parameter 'limit' must be between %d and %d."
            % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    elif offset < 0:
        invalid_pagination("Query parameter 'offset' must be >= 0.")
    return limit, offset


def enum_filter(name, choices):
    """Read an enum-typed query filter, rejecting values outside the declared set."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in choices:
        invalid_enum(
            "Query parameter '%s' must be one of: %s." % (name, ", ".join(choices)))
    return raw


def bool_filter(name):
    """Read a boolean query filter; anything other than true/false is not an enum error."""
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    invalid_request("Query parameter '%s' must be true or false." % name)


def str_filter(name):
    return request.args.get(name)


def month_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw
