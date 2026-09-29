"""Payload-shape validation (PRD 2.7 band 3 -> ERR_INVALID_REQUEST)."""
import re
from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_date, parse_instant
from errors import ApiError

# ---- declared enum sets ---------------------------------------------------
DEFECT_TYPES = ("SAFETY_DEFECT", "NONCOMPLIANCE")
RISK_SEVERITIES = ("HIGH", "MODERATE", "LOW")
CAMPAIGN_STATUSES = (
    "DRAFT", "DEFECT_DETERMINED", "FILED", "INTERIM_NOTIFIED",
    "OWNER_NOTIFIED", "MONITORING", "CLOSED", "SUPERSEDED",
)
REMEDY_STATUSES = (
    "REMEDY_UNDER_DEVELOPMENT", "INTERIM_ONLY", "REMEDY_RELEASED", "REMEDY_REVISED",
)
INCLUSION_MODES = ("INCLUDE", "EXCLUDE")
REGION_CODES = ("NE", "SE", "MW", "WE")
SALE_STATUSES = ("IN_DEALER_STOCK", "SOLD", "EXPORTED", "SCRAPPED")
AV_REMEDY_STATUSES = (
    "UNREPAIRED", "SCHEDULED", "REMEDIED", "UNREACHABLE", "REMOVED_FROM_POPULATION",
)
WAVE_TYPES = ("INTERIM", "REMEDY", "FOLLOW_UP")
WAVE_STATUSES = ("PLANNED", "RELEASE_APPROVED", "MAILED", "CANCELLED")
DEALER_STATUSES = ("ACTIVE", "SUSPENDED")
ALLOCATION_STATUSES = ("ALLOCATED", "REVOKED")
RATE_TYPES = ("WARRANTY", "PREVAILING")
CLAIM_STATUSES = ("SUBMITTED", "APPROVED", "REJECTED", "REVERSED")
REIMBURSEMENT_STATUSES = ("SUBMITTED", "DOCUMENTS_REQUESTED", "APPROVED", "DENIED")
OUTREACH_CHANNELS = ("MAIL", "PHONE", "EMAIL", "CANVASS")
OUTREACH_OUTCOMES = ("NO_RESPONSE", "BAD_ADDRESS", "SCHEDULED", "OWNER_REFUSED")
FILING_TYPES = ("DEFECT_NOTICE", "QUARTERLY", "AMENDMENT")
FILING_STATUSES = ("SUBMITTED", "AMENDED")
DECISIONS_CLAIM = ("APPROVE", "REJECT")
DECISIONS_REIMBURSEMENT = ("APPROVE", "DENY")

CAMPAIGN_NUMBER_RE = re.compile(r"^[0-9]{2}V-[0-9]{3}$")
REPORT_PERIOD_RE = re.compile(r"^[0-9]{4}Q[1-4]$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be valid JSON.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name, min_len=1, max_len=None):
    if not present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if len(value) < min_len:
        bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    return value


def opt_str(payload, name, default=None, min_len=1, max_len=None):
    if not present(payload, name):
        return default
    return req_str(payload, name, min_len=min_len, max_len=max_len)


def req_enum(payload, name, allowed):
    value = req_str(payload, name)
    if value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    return req_enum(payload, name, allowed)


def req_bool(payload, name):
    if not present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def opt_bool(payload, name, default=None):
    if not present(payload, name):
        return default
    return req_bool(payload, name)


def req_int(payload, name, minimum=None, maximum=None):
    if not present(payload, name):
        bad("%s is required." % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s." % (name, maximum))
    return value


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        return default
    return req_int(payload, name, minimum=minimum, maximum=maximum)


def _to_decimal(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("%s must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("%s must be a number." % name)
    if not dec.is_finite():
        bad("%s must be a finite number." % name)
    return dec


def req_decimal(payload, name, gt=None, ge=None):
    if not present(payload, name):
        bad("%s is required." % name)
    dec = _to_decimal(name, payload[name])
    if gt is not None and dec <= Decimal(str(gt)):
        bad("%s must be greater than %s." % (name, gt))
    if ge is not None and dec < Decimal(str(ge)):
        bad("%s must be >= %s." % (name, ge))
    return dec


def opt_decimal(payload, name, default=None, gt=None, ge=None):
    if not present(payload, name):
        return default
    return req_decimal(payload, name, gt=gt, ge=ge)


def req_date_str(payload, name):
    value = req_str(payload, name)
    parsed = parse_date(value)
    if parsed is None:
        bad("%s must be a calendar date in YYYY-MM-DD form." % name)
    return value, parsed


def opt_date_str(payload, name):
    if not present(payload, name):
        return None, None
    return req_date_str(payload, name)


def req_instant_str(payload, name):
    value = req_str(payload, name)
    parsed = parse_instant(value)
    if parsed is None:
        bad("%s must be an ISO 8601 UTC instant." % name)
    return value, parsed


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_date(name):
    value = request.args.get(name)
    if value is None:
        return None
    parsed = parse_date(value)
    if parsed is None:
        bad("%s must be a calendar date in YYYY-MM-DD form." % name)
    return parsed
