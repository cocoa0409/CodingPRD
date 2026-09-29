"""Body / query parsing and field validation (rejection ladder priority 4)."""

import re
from decimal import Decimal, InvalidOperation

from flask import request

import errors
from errors import fail
from util import dec, parse_dt

MISSING = object()

CODE_RE = re.compile(r"^[A-Z0-9\-]{2,16}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")

PRODUCT_CLASSES = ("PROTEIN", "PRODUCE", "FROZEN", "DRY_GROCERY", "DISPOSABLES", "BEVERAGE", "SPECIALTY")
COST_BASES = ("LAST_COST", "AVG_COST", "REPLACEMENT_COST")
MARKUP_TYPES = ("PERCENT_OF_COST", "DOLLARS_PER_CASE")
COVERAGE_TYPES = ("IN_MARKET", "OUT_OF_MARKET")
BILL_BACK_BASES = ("FIXED_NET_PRICE", "COST_PLUS_PROTECTED")
PRICE_PROTECTION_MODES = ("HOLD_CONTRACT_PRICE", "SUBSTITUTE_OWN_PRICE")
COMPLIANCE_BASES = ("DOLLAR_WEIGHTED", "CASE_WEIGHTED")
REMIT_METHODS = ("CHECK", "ACH", "CREDIT_MEMO")
PARTY_STATUSES = ("ACTIVE", "SUSPENDED")
PRODUCT_STATUSES = ("ACTIVE", "DISCONTINUED")
STOCK_STATUSES = ("IN_STOCK", "OUT_OF_STOCK")
CONTRACT_STATUSES = ("DRAFT", "PENDING_SIGNATURE", "ACTIVE", "AMENDING", "SUSPENDED", "EXPIRED", "TERMINATED")
TIER_STATUSES = ("ACTIVE", "SUPERSEDED")
COVERAGE_STATUSES = ("ACTIVE", "ENDED")
DEVIATION_STATUSES = (
    "DRAFT", "SUBMITTED", "MANUFACTURER_APPROVED", "REVISION_REQUESTED", "REJECTED",
    "ACTIVE", "PRICE_CEILING_BREACHED", "EXPIRED", "TERMINATED",
)
RULE_STATUSES = ("ACTIVE", "RETIRED")
NOTICE_STATUSES = ("PENDING", "ACKNOWLEDGED", "DISPUTED", "EFFECTIVE", "WITHDRAWN")
PERIOD_STATUSES = ("OPEN", "CLOSED", "SETTLED")
PRICING_STATUSES = ("DRAFT_PRICED", "INVOICED", "REPRICED", "CREDITED")
BILLBACK_STATUSES = ("NOT_APPLICABLE", "ACCRUED", "CLAIMED", "RECOVERED", "WRITTEN_OFF")
CLAIM_STATUSES = ("ACCRUED", "SUBMITTED", "PARTIALLY_RECOVERED", "RECOVERED", "DISPUTED", "WRITTEN_OFF")
REMITTANCE_STATUSES = ("APPLIED", "REVERSED")
DISPUTE_STATUSES = ("OPEN", "UNDER_AUDIT", "UPHELD", "REJECTED", "CREDIT_ISSUED", "WITHDRAWN")
DISPUTE_REASONS = ("TIER_MISAPPLIED", "DEVIATION_NOT_APPLIED", "COST_BASIS_WRONG", "SERVICE_FEE_WRONG")
DECISIONS = ("APPROVE", "REQUEST_REVISION", "REJECT")
RESOLUTIONS = ("UPHELD", "REJECTED")


def body(allowed=()):
    """Parse the JSON body, rejecting anything that is not an object and any
    field outside the endpoint's declared input list."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    for key in parsed:
        if key not in allowed:
            fail(errors.ERR_INVALID_REQUEST, "Unknown field '%s'." % key)
    return parsed


def present(data, key):
    return key in data and data[key] is not None


def raw_fk(data, key):
    """Fetch a foreign-key value for the existence pass. A missing or non-string
    value is left to the priority-4 validation pass."""
    value = data.get(key)
    if isinstance(value, str):
        return value
    return None


def _required(data, key, required, default):
    if key not in data or data[key] is None:
        if required:
            fail(errors.ERR_INVALID_REQUEST, "Field '%s' is required." % key)
        return MISSING if default is MISSING else default
    return data[key]


def get_str(data, key, required=True, default=None, allow_empty=False):
    value = _required(data, key, required, default)
    if value is MISSING or value is None:
        return value
    if not isinstance(value, str):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must not be empty." % key)
    return value


def get_code(data, key, required=True):
    value = get_str(data, key, required=required)
    if isinstance(value, str) and not CODE_RE.match(value):
        fail(errors.ERR_INVALID_REQUEST,
             "Field '%s' must be 2-16 uppercase alphanumeric or hyphen characters." % key)
    return value


def get_int(data, key, required=True, default=None, minimum=None, maximum=None):
    value = _required(data, key, required, default)
    if value is MISSING or value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be <= %s." % (key, maximum))
    return value


def get_decimal(data, key, required=True, default=None, minimum=None, maximum=None,
                places=2, exclusive_minimum=None):
    value = _required(data, key, required, default)
    if value is MISSING or value is None:
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a number." % key)
    try:
        number = dec(value)
    except (InvalidOperation, ValueError):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a number." % key)
    if number != number or number.is_infinite():
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a finite number." % key)
    if places is not None and -number.as_tuple().exponent > places:
        fail(errors.ERR_INVALID_REQUEST,
             "Field '%s' carries at most %d decimal places." % (key, places))
    if minimum is not None and number < dec(minimum):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be >= %s." % (key, minimum))
    if exclusive_minimum is not None and number <= dec(exclusive_minimum):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be > %s." % (key, exclusive_minimum))
    if maximum is not None and number > dec(maximum):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be <= %s." % (key, maximum))
    return number


def get_bool(data, key, required=True, default=None):
    value = _required(data, key, required, default)
    if value is MISSING or value is None:
        return value
    if not isinstance(value, bool):
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a boolean." % key)
    return value


def get_enum(data, key, allowed_values, required=True, default=None):
    value = _required(data, key, required, default)
    if value is MISSING or value is None:
        return value
    if not isinstance(value, str) or value not in allowed_values:
        fail(errors.ERR_INVALID_REQUEST,
             "Field '%s' must be one of %s." % (key, ", ".join(allowed_values)))
    return value


def get_dt(data, key, required=True, default=None):
    value = _required(data, key, required, default)
    if value is MISSING or value is None:
        return value
    parsed = parse_dt(value)
    if parsed is None:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 instant." % key)
    return parsed


def get_state_list(data, key, required=True):
    value = _required(data, key, required, None)
    if value is None:
        return value
    if not isinstance(value, list) or len(value) == 0:
        fail(errors.ERR_INVALID_REQUEST, "Field '%s' must be a non-empty array." % key)
    for item in value:
        if not isinstance(item, str) or not STATE_RE.match(item):
            fail(errors.ERR_INVALID_REQUEST,
                 "Field '%s' must contain two-letter uppercase state codes." % key)
    return list(value)


# --- query parameters -------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail(errors.ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail(errors.ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            fail(errors.ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit, offset


def query_value(key):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    return value


def query_enum(key, allowed_values):
    value = query_value(key)
    if value is None:
        return None
    if value not in allowed_values:
        fail(errors.ERR_INVALID_REQUEST, "%s must be one of %s." % (key, ", ".join(allowed_values)))
    return value


def paginate(rows):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, limit, offset, total
