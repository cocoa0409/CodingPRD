"""Request shape validation (PRD 2.10 priority 4) and enumerated vocabularies."""
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

UTC = timezone.utc

ACCREDITATION_BODIES = ["ANAB_CFP", "ANSI_LEGACY", "STATE_ONLY"]
LANGUAGES = ["EN", "ES", "ZH", "VI"]
PROCTOR_ROLES = ["PROCTOR", "INSTRUCTOR"]
EXAM_FORM_STATUS = ["ACTIVE", "RETIRED"]
COMPLIANCE_STATUS = ["NOT_CERTIFIED", "CERTIFIED", "LAPSED", "NON_COMPLIANT"]
REGISTRATION_STATUS = ["PENDING", "REGISTERED", "REJECTED", "UNDER_AUDIT",
                       "SUSPENDED", "REVOKED"]
SUSPENDED_REASON = ["AUDIT_FAILURE", "RISK_THRESHOLD_BREACH"]
RISK_VARIANTS = ["ROLLING_WINDOW", "LIFETIME_CUMULATIVE"]
BATCH_STATUS = ["ACTIVE", "DEPLETED", "EXPIRED", "VOIDED"]
CODE_STATUS = ["AVAILABLE", "ASSIGNED", "CONSUMED", "VOIDED", "EXPIRED"]
BUNDLE_TYPES = ["EXAM_ONLY", "COURSE_PLUS_EXAM"]
ACCOMMODATION_TYPES = ["EXTRA_TIME", "READER_ASSIST", "SEPARATE_ROOM",
                       "TRANSLATED_FORM"]
ACCOMMODATION_STATUS = ["REQUESTED", "UNDER_REVIEW", "APPROVED", "DENIED"]
DELIVERY_MODES = ["IN_PERSON", "REMOTE"]
SESSION_STATUS = ["SCHEDULED", "CHECKED_IN", "IN_PROGRESS", "SUBMITTED",
                  "CLOSED", "CANCELLED", "INVALIDATED"]
PROCTORING_STATUS = ["PENDING_ASSIGNMENT", "ASSIGNED", "PENDING_REPROCTOR",
                     "ATTESTED", "INCIDENT_UNDER_REVIEW", "CLEARED",
                     "COMPROMISED"]
ID_DOCUMENT_TYPES = ["GOVT_PHOTO_ID", "PASSPORT", "MILITARY_ID"]
SCORE_REPORT_STATUS = ["PROVISIONAL", "FINAL", "VOIDED"]
INCIDENT_CATEGORIES = ["IMPERSONATION", "PROHIBITED_MATERIAL",
                       "ROOM_SCAN_REFUSAL", "CONTENT_DISCLOSURE"]
INCIDENT_SEVERITIES = ["MINOR", "MAJOR", "CRITICAL"]
INCIDENT_STATUS = ["OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED"]
CERTIFICATE_STATUS = ["ISSUED", "EXPIRED", "REVOKED", "SUPERSEDED"]
REVOCATION_REASONS = ["SCORE_VOIDED", "JURISDICTION_WITHDRAWAL"]
REMINDER_TIERS = ["T_180", "T_90", "T_30", "T_LAPSED"]
LOCAL_REGISTRATION_STATUS = ["FILED", "POSTED", "VERIFIED", "REJECTED",
                             "DELINQUENT", "WITHDRAWN"]

SEVERITY_WEIGHT = {"MINOR": 1, "MAJOR": 3, "CRITICAL": 5}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        bad("request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("request body must be a JSON object")
    return parsed


def present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, min_len=1, max_len=None):
    if not present(body, name):
        bad("%s is required" % name)
    value = body[name]
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if len(value) < min_len:
        bad("%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (name, max_len))
    return value


def opt_str(body, name, min_len=1, max_len=None, default=None):
    if not present(body, name):
        return default
    return req_str(body, name, min_len, max_len)


def req_id(body, name):
    if not present(body, name):
        bad("%s is required" % name)
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be a non-empty string" % name)
    return value


def opt_id(body, name, default=None):
    if not present(body, name):
        return default
    return req_id(body, name)


def req_enum(body, name, allowed):
    if not present(body, name):
        bad("%s is required" % name)
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


def _as_int(name, value):
    if isinstance(value, bool):
        bad("%s must be an integer" % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    bad("%s must be an integer" % name)


def req_int(body, name, lo=None, hi=None):
    if not present(body, name):
        bad("%s is required" % name)
    value = _as_int(name, body[name])
    if lo is not None and value < lo:
        bad("%s must be >= %s" % (name, lo))
    if hi is not None and value > hi:
        bad("%s must be <= %s" % (name, hi))
    return value


def opt_int(body, name, lo=None, hi=None, default=None):
    if not present(body, name):
        return default
    return req_int(body, name, lo, hi)


def req_bool(body, name):
    if not present(body, name):
        bad("%s is required" % name)
    value = body[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def opt_bool(body, name, default=None):
    if not present(body, name):
        return default
    return req_bool(body, name)


def _as_decimal(name, value, max_dp):
    if isinstance(value, bool):
        bad("%s must be a number" % name)
    if not isinstance(value, (int, float, str)):
        bad("%s must be a number" % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("%s must be a number" % name)
    if dec != dec.to_integral_value() or True:
        exponent = dec.as_tuple().exponent
        if isinstance(exponent, int) and -exponent > max_dp:
            bad("%s carries at most %d decimals" % (name, max_dp))
    return dec


def req_decimal(body, name, lo, hi, max_dp):
    if not present(body, name):
        bad("%s is required" % name)
    dec = _as_decimal(name, body[name], max_dp)
    if dec < Decimal(str(lo)) or dec > Decimal(str(hi)):
        bad("%s must be between %s and %s" % (name, lo, hi))
    return dec


def opt_decimal(body, name, lo, hi, max_dp, default=None):
    if not present(body, name):
        return default
    return req_decimal(body, name, lo, hi, max_dp)


def parse_datetime(name, value):
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be an ISO 8601 UTC datetime" % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad("%s must be an ISO 8601 UTC datetime" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def req_datetime(body, name):
    if not present(body, name):
        bad("%s is required" % name)
    return parse_datetime(name, body[name])


def opt_datetime(body, name, default=None):
    if not present(body, name):
        return default
    return req_datetime(body, name)


def req_date_string(body, name):
    if not present(body, name):
        bad("%s is required" % name)
    value = body[name]
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        bad("%s must be a YYYY-MM-DD date" % name)
    text = value.strip()
    try:
        date.fromisoformat(text)
    except ValueError:
        bad("%s must be a YYYY-MM-DD date" % name)
    return text


def req_enum_subset(body, name, allowed):
    if not present(body, name):
        bad("%s is required" % name)
    value = body[name]
    if not isinstance(value, list) or len(value) == 0:
        bad("%s must be a non-empty array" % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad("%s entries must be one of %s" % (name, ", ".join(allowed)))
    return list(value)


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(allowed)))
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
    bad("%s must be true or false" % name)


def query_id(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
