"""Schema validation helpers — PRD 2.9 rule 3 (ERR_INVALID_REQUEST, 400)."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import invalid

_DATE_RE = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$")
_INT_RE = re.compile(r"^[+-]?\d+$")

JOB_FAMILIES = ["ENGINEERING", "OPERATIONS", "CLINICAL", "RETAIL_FRONTLINE", "CORPORATE"]
SKILL_TRACKS = ["DATA_ANALYTICS", "NURSING", "SUPPLY_CHAIN", "CYBERSECURITY", "BUSINESS_ADMIN"]
CREDENTIAL_TYPES = ["CERTIFICATE", "ASSOCIATE", "BACHELOR", "MASTER"]
RISK_FLAGS = [
    "FINANCIAL_STRESS",
    "SCHEDULE_CONFLICT",
    "ACADEMIC_STRUGGLE",
    "LOW_ENGAGEMENT",
    "CARE_RESPONSIBILITY",
]
MODALITIES = ["PHONE", "VIDEO", "IN_PERSON", "ASYNC_MESSAGE"]
FUNDING_MODELS = ["DIRECT_BILL", "REIMBURSEMENT"]
POLICY_FUNDING_MODELS = ["DIRECT_BILL", "REIMBURSEMENT", "HYBRID"]
EMPLOYMENT_STATUSES = ["ACTIVE", "LEAVE", "TERMINATED"]
ACCREDITATION_STATUSES = ["ACCREDITED", "PROBATION", "UNACCREDITED"]
COMPLETION_STATUSES = ["PASSED", "FAILED", "WITHDRAWN", "INCOMPLETE"]

_MISSING = object()


def body():
    """Parsed JSON object body; an absent body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        parsed = None
    if parsed is None:
        invalid("request body must be a JSON object")
    if not isinstance(parsed, dict):
        invalid("request body must be a JSON object")
    return parsed


def _present(data, field):
    return field in data and data[field] is not None


def _require(data, field):
    if field not in data or data[field] is None:
        invalid("field '%s' is required" % field)
    return data[field]


def string_field(data, field, required=True, min_len=1, max_len=None, default=_MISSING, allow_blank=False):
    if not _present(data, field):
        if required:
            _require(data, field)
        return None if default is _MISSING else default
    value = data[field]
    if not isinstance(value, str):
        invalid("field '%s' must be a string" % field)
    if not allow_blank and value.strip() == "" and min_len > 0:
        invalid("field '%s' must not be blank" % field)
    if min_len is not None and len(value) < min_len:
        invalid("field '%s' is too short" % field)
    if max_len is not None and len(value) > max_len:
        invalid("field '%s' is too long" % field)
    return value


def id_field(data, field, required=True):
    return string_field(data, field, required=required, min_len=1, max_len=None)


def email_field(data, field, required=True):
    value = string_field(data, field, required=required, min_len=1, max_len=320)
    if value is not None and "@" not in value:
        invalid("field '%s' must contain '@'" % field)
    return value


def int_field(data, field, required=True, minimum=None, maximum=None, default=_MISSING):
    if not _present(data, field):
        if required:
            _require(data, field)
        return None if default is _MISSING else default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("field '%s' must be an integer" % field)
    if minimum is not None and value < minimum:
        invalid("field '%s' must be >= %s" % (field, minimum))
    if maximum is not None and value > maximum:
        invalid("field '%s' must be <= %s" % (field, maximum))
    return value


def number_field(data, field, required=True, minimum=None, maximum=None, decimals=None,
                 default=_MISSING, exclusive_min=None):
    if not _present(data, field):
        if required:
            _require(data, field)
        return None if default is _MISSING else default
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("field '%s' must be a number" % field)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        invalid("field '%s' must be a number" % field)
    if decimals is not None and -dec.as_tuple().exponent > decimals:
        invalid("field '%s' accepts at most %d decimal places" % (field, decimals))
    if minimum is not None and dec < Decimal(str(minimum)):
        invalid("field '%s' must be >= %s" % (field, minimum))
    if exclusive_min is not None and dec <= Decimal(str(exclusive_min)):
        invalid("field '%s' must be > %s" % (field, exclusive_min))
    if maximum is not None and dec > Decimal(str(maximum)):
        invalid("field '%s' must be <= %s" % (field, maximum))
    return value


def bool_field(data, field, required=True, default=_MISSING):
    if not _present(data, field):
        if required:
            _require(data, field)
        return None if default is _MISSING else default
    value = data[field]
    if not isinstance(value, bool):
        invalid("field '%s' must be a boolean" % field)
    return value


def enum_field(data, field, allowed, required=True, default=_MISSING):
    if not _present(data, field):
        if required:
            _require(data, field)
        return None if default is _MISSING else default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        invalid("field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return value


def date_field(data, field, required=True, default=_MISSING):
    if not _present(data, field):
        if required:
            _require(data, field)
        return None if default is _MISSING else default
    value = data[field]
    if not isinstance(value, str) or not _DATE_RE.match(value):
        invalid("field '%s' must be an ISO 8601 date" % field)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        invalid("field '%s' must be an ISO 8601 date" % field)
    return parsed


def array_field(data, field, allowed, required=True, default=_MISSING, non_empty=True):
    if not _present(data, field):
        if required:
            _require(data, field)
        return None if default is _MISSING else list(default)
    value = data[field]
    if not isinstance(value, list):
        invalid("field '%s' must be an array" % field)
    if non_empty and len(value) == 0:
        invalid("field '%s' must not be empty" % field)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            invalid("field '%s' must be a subset of %s" % (field, ", ".join(allowed)))
        if item in seen:
            invalid("field '%s' must not contain duplicates" % field)
        seen.add(item)
    return list(value)


def nullable_text(data, field, max_len, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        invalid("field '%s' must be a string" % field)
    if len(value) > max_len:
        invalid("field '%s' is too long" % field)
    return value


def parse_iso_instant(data, field):
    value = _require(data, field)
    if not isinstance(value, str):
        invalid("field '%s' must be an ISO 8601 instant" % field)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        invalid("field '%s' must be an ISO 8601 instant" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_date(value):
    """Parse a stored ISO date string back into a date object."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_str(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


# --------------------------------------------------------------------------- #
# query parameters
# --------------------------------------------------------------------------- #

def query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not _INT_RE.match(raw):
        invalid("query parameter '%s' must be an integer" % name)
    value = int(raw)
    if minimum is not None and value < minimum:
        invalid("query parameter '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        invalid("query parameter '%s' must be <= %s" % (name, maximum))
    return value


def pagination():
    limit = query_int("limit", 10, 1, 100)
    offset = query_int("offset", 0, 0, None)
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        invalid("query parameter '%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def query_str(name):
    return request.args.get(name)
