"""Request-shape validation (PRD 2.3, 2.11 -- priority 3) and id resolution."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail, invalid
import store as st

# --- enum vocabularies -----------------------------------------------------
TRACKS = ("ON_PREMISE", "OFF_PREMISE")
DELIVERY_MODES = ("CLASSROOM", "ONLINE")
MANDATE_TYPES = ("MANDATORY", "CONDITIONAL", "VOLUNTARY")
COURSE_STATUSES = ("DRAFT", "PUBLISHED", "RETIRED")
APPROVAL_STATUSES = (
    "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "REJECTED",
    "STALE", "SUPERSEDED", "EXPIRED",
)
DECISIONS = ("APPROVE", "REQUEST_CHANGES", "REJECT")
TRAINER_STATUSES = ("PROVISIONAL", "CERTIFIED", "SUSPENDED", "LAPSED")
SESSION_STATUSES = ("SCHEDULED", "ROSTER_LOCKED", "EXAM_OPEN", "COMPLETED", "CANCELLED")
ENROLLMENT_STATES = (
    "REGISTERED", "ATTENDED", "NO_SHOW", "EXAM_SCHEDULED", "EXAM_IN_PROGRESS",
    "EXAM_FAILED", "PASSED", "INCOMPLETE", "WITHDRAWN",
)
ATTEMPT_OUTCOMES = ("IN_PROGRESS", "PASS", "FAIL", "VOIDED")
WORK_ELIGIBILITIES = ("UNCERTIFIED", "ELIGIBLE", "GRACE", "RESTRICTED")
VALIDITY_STATES = ("ACTIVE", "GRACE", "LAPSED", "SUSPENDED", "SUPERSEDED")
REGISTRY_STATES = (
    "NOT_REQUIRED", "PENDING_SUBMISSION", "SUBMITTED", "ACCEPTED", "RESUBMIT_REQUIRED",
)
ACK_RESULTS = ("ACCEPTED", "REJECTED")
REJECTION_CODES = (
    "NONE", "DUPLICATE_SERVER_RECORD", "INVALID_COURSE_APPROVAL", "NAME_MISMATCH",
)
ACCOUNT_STATUSES = ("ACTIVE", "DELINQUENT", "SUSPENDED")
POSTURES = ("COMPLIANT", "AT_RISK", "NON_COMPLIANT", "NOT_APPLICABLE")
ASSIGNMENT_STATES = ("ACTIVE", "WORK_RESTRICTED", "ENDED")
RESTRICTION_REASONS = ("NONE", "CERTIFICATE_LAPSED", "REGISTRY_SUSPENDED", "NO_CERTIFICATE")
DOCUMENT_STATES = ("ISSUED", "SUPERSEDED", "VOIDED")
DISCOUNT_TIERS = ("NONE", "TIER_1", "TIER_2", "TIER_3")

_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


# --- entity families (PRD 2.9) --------------------------------------------
FAMILY_ERROR = {
    "courses": "ERR_CATALOG_NOT_FOUND",
    "course_approvals": "ERR_CATALOG_NOT_FOUND",
    "state_jurisdictions": "ERR_CATALOG_NOT_FOUND",
    "class_sessions": "ERR_TRAINING_NOT_FOUND",
    "enrollments": "ERR_TRAINING_NOT_FOUND",
    "exam_attempts": "ERR_TRAINING_NOT_FOUND",
    "trainers": "ERR_CREDENTIAL_NOT_FOUND",
    "alcohol_servers": "ERR_CREDENTIAL_NOT_FOUND",
    "certificates": "ERR_CREDENTIAL_NOT_FOUND",
    "registry_submissions": "ERR_CREDENTIAL_NOT_FOUND",
    "employer_accounts": "ERR_EMPLOYER_NOT_FOUND",
    "employer_locations": "ERR_EMPLOYER_NOT_FOUND",
    "server_assignments": "ERR_EMPLOYER_NOT_FOUND",
    "dram_shop_documents": "ERR_EMPLOYER_NOT_FOUND",
}


def must_exist(kind, row_id):
    row = st.get(kind, row_id)
    if row is None:
        fail(FAMILY_ERROR[kind], "%s '%s' does not resolve." % (kind, row_id))
    return row


# --- body access -----------------------------------------------------------

def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        invalid("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        invalid("Request body must be a JSON object.")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, min_len=1, max_len=None):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % key)
    if len(value) < min_len or (max_len is not None and len(value) > max_len):
        invalid("Field '%s' has an invalid length." % key)
    return value


def opt_str(data, key, min_len=1, max_len=None, default=None):
    if not _present(data, key):
        return default
    return req_str(data, key, min_len, max_len)


def req_enum(data, key, allowed):
    value = req_str(data, key, 1, None)
    if value not in allowed:
        invalid("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def _as_int(value, key):
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % key)
    return value


def req_int(data, key, low=None, high=None):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    value = _as_int(data[key], key)
    if low is not None and value < low:
        invalid("Field '%s' is below its minimum." % key)
    if high is not None and value > high:
        invalid("Field '%s' is above its maximum." % key)
    return value


def opt_int(data, key, low=None, high=None, default=None):
    if not _present(data, key):
        return default
    return req_int(data, key, low, high)


def _as_decimal(value, key):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        invalid("Field '%s' must be a number." % key)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        invalid("Field '%s' must be a number." % key)


def req_decimal(data, key, low=None, high=None, places=2):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    value = _as_decimal(data[key], key)
    if low is not None and value < low:
        invalid("Field '%s' is below its minimum." % key)
    if high is not None and value > high:
        invalid("Field '%s' is above its maximum." % key)
    return quantize(value, places)


def opt_decimal(data, key, low=None, high=None, places=2, default=None):
    if not _present(data, key):
        return default
    return req_decimal(data, key, low, high, places)


def quantize(value, places=2):
    from calcs import round_half_up
    return round_half_up(value, places)


def req_bool(data, key):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % key)
    return value


def opt_bool(data, key, default=None):
    if not _present(data, key):
        return default
    return req_bool(data, key)


def parse_dt(raw, key):
    if not isinstance(raw, str):
        invalid("Field '%s' must be an ISO 8601 datetime string." % key)
    text = raw.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        invalid("Field '%s' must be an ISO 8601 datetime string." % key)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def req_dt(data, key):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    return parse_dt(data[key], key)


def opt_dt(data, key, default=None):
    if not _present(data, key):
        return default
    return req_dt(data, key)


def req_enum_array(data, key, allowed, allow_empty=True):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, list):
        invalid("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            invalid("Field '%s' contains an unknown member." % key)
    if not allow_empty and len(value) == 0:
        invalid("Field '%s' must not be empty." % key)
    return list(value)


def req_string_array(data, key, allow_empty=True):
    if not _present(data, key):
        invalid("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, list):
        invalid("Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str):
            invalid("Field '%s' must contain strings." % key)
    if not allow_empty and len(value) == 0:
        invalid("Field '%s' must not be empty." % key)
    return list(value)


def req_state_code(data, key):
    value = req_str(data, key, 1, None)
    if not _STATE_CODE_RE.match(value):
        invalid("Field '%s' must be exactly two uppercase letters." % key)
    return value


def req_email(data, key):
    value = req_str(data, key, 1, None)
    if "@" not in value:
        invalid("Field '%s' must contain an at-sign." % key)
    return value


# --- query parameters ------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            invalid("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            invalid("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            invalid("Query parameter 'offset' must not be negative.")
    return limit, offset


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_enum(name, allowed):
    value = q_str(name)
    if value is None:
        return None
    if value not in allowed:
        invalid("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value
