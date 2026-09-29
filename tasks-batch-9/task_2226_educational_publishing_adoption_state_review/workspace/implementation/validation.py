"""Request-shape validation (priority 3 - ERR_INVALID_REQUEST)."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail

CODE_RE = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)*$")
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
INT_RE = re.compile(r"^[+-]?\d+$")

SUBJECTS = ("MATH", "ELA", "SCIENCE", "SOCIAL_STUDIES")
ADOPTION_MODELS = ("ADOPTION_LIST", "OPEN_TERRITORY")
ACCESSIBILITY_STANDARDS = ("WCAG_2_1_AA", "WCAG_2_2_AA")
ACCESSIBILITY_CONFORMANCE = ("WCAG_2_1_AA", "WCAG_2_2_AA", "NONE")
ROSTERING_STANDARDS = ("ONEROSTER_1_1", "ONEROSTER_1_2", "CSV_MANUAL")
CYCLE_STATUSES = (
    "SCHEDULED",
    "OPEN",
    "CLOSED_FOR_SUBMISSION",
    "IN_REVIEW",
    "PUBLIC_COMMENT",
    "DECIDED",
    "ARCHIVED",
)
TITLE_STATUSES = ("DRAFT", "ACTIVE", "REVISION_PLANNED", "SUNSET")
EDIT_TYPES = ("ADD_REQUIRED_TOPIC", "REMOVE_PROHIBITED_TAG", "REGIONAL_SUBSTITUTION")
EDIT_STATUSES = ("PROPOSED", "APPROVED", "REJECTED", "APPLIED", "REVERTED")
REVIEW_STATUSES = (
    "DRAFT",
    "FILED",
    "SCHEDULED",
    "PRESENTED",
    "ADOPTED",
    "ADOPTED_WITH_CONDITIONS",
    "NOT_ADOPTED",
    "WITHDRAWN",
)
PRICING_STATUSES = ("UNPRICED", "PRICE_FILED", "PRICE_APPROVED", "PRICE_REJECTED")
SAMPLING_STATUSES = ("NOT_REQUIRED", "PENDING", "PARTIAL", "SHIPPED")
DEPTH_LEVELS = ("MENTION", "PRACTICE", "MASTERY")
REVIEWER_VERDICTS = ("PENDING", "ACCEPTED", "INSUFFICIENT")
PANEL_STATUSES = ("SCHEDULED", "IN_SESSION", "CLOSED")
SLOT_STATUSES = ("RESERVED", "PRESENTED", "TALLIED", "NO_SHOW", "CANCELLED")
TALLY_OUTCOMES = ("PENDING", "RECOMMEND", "RECOMMEND_WITH_CONDITIONS", "REJECT")
VOTES = ("RECOMMEND", "RECOMMEND_WITH_CONDITIONS", "REJECT", "ABSTAIN")
COMMENT_CATEGORIES = ("ERROR_OF_FACT", "BIAS_CONCERN", "PROHIBITED_CONTENT", "OTHER")
COMMENT_SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
COMMENT_STATUSES = ("OPEN", "ESCALATED", "RESPONDED")
PROPOSAL_STATUSES = ("FILED", "APPROVED", "REJECTED", "SUPERSEDED")
ORDER_STATUSES = ("QUOTED", "CONFIRMED", "FULFILLED", "CANCELLED")

_MISSING = object()


def body():
    """Parse the JSON body; absent body is treated as an empty object."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(field, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def _present(payload, field, required, default):
    if field not in payload or payload[field] is None:
        if required:
            _bad(field, "is required")
        return _MISSING if default is _MISSING else default
    return payload[field]


def get_str(payload, field, min_len=1, max_len=None, required=True, default=_MISSING,
            pattern=None, exact_len=None):
    value = _present(payload, field, required, default)
    if value is _MISSING or (field not in payload or payload[field] is None):
        return value if value is not _MISSING else None
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if exact_len is not None and len(value) != exact_len:
        _bad(field, "must be exactly %d characters" % exact_len)
    if min_len is not None and len(value) < min_len:
        _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters" % max_len)
    if pattern is not None and not pattern.match(value):
        _bad(field, "has an invalid format")
    return value


def get_int(payload, field, minimum=None, maximum=None, required=True, default=_MISSING):
    value = _present(payload, field, required, default)
    if value is _MISSING or (field not in payload or payload[field] is None):
        return value if value is not _MISSING else None
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %s" % maximum)
    return value


def get_decimal(payload, field, minimum=None, maximum=None, required=True,
                default=_MISSING, places=2):
    value = _present(payload, field, required, default)
    if value is _MISSING or (field not in payload or payload[field] is None):
        return value if value is not _MISSING else None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _bad(field, "must be a number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(field, "must be a number")
    if not number.is_finite():
        _bad(field, "must be a finite number")
    if minimum is not None and number < Decimal(str(minimum)):
        _bad(field, "must be at least %s" % minimum)
    if maximum is not None and number > Decimal(str(maximum)):
        _bad(field, "must be at most %s" % maximum)
    from calc import round_half_up

    return round_half_up(number, places)


def get_bool(payload, field, required=True, default=_MISSING):
    value = _present(payload, field, required, default)
    if value is _MISSING or (field not in payload or payload[field] is None):
        return value if value is not _MISSING else None
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def get_enum(payload, field, choices, required=True, default=_MISSING):
    value = _present(payload, field, required, default)
    if value is _MISSING or (field not in payload or payload[field] is None):
        return value if value is not _MISSING else None
    if not isinstance(value, str) or value not in choices:
        _bad(field, "must be one of %s" % ", ".join(choices))
    return value


def get_code_array(payload, field, max_entries, required=False, default=None):
    if field not in payload or payload[field] is None:
        if required:
            _bad(field, "is required")
        return list(default) if default is not None else []
    value = payload[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    if len(value) > max_entries:
        _bad(field, "must contain at most %d entries" % max_entries)
    for item in value:
        if not isinstance(item, str) or not CODE_RE.match(item):
            _bad(field, "must contain uppercase snake_case codes")
        if len(item) < 1 or len(item) > 40:
            _bad(field, "codes must be 1 to 40 characters")
    return list(value)


def parse_datetime(value, field):
    if not isinstance(value, str):
        _bad(field, "must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _bad(field, "must be a parseable ISO 8601 datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_datetime(payload, field, required=True, default=_MISSING):
    value = _present(payload, field, required, default)
    if value is _MISSING or (field not in payload or payload[field] is None):
        return value if value is not _MISSING else None
    return parse_datetime(value, field)


def pagination():
    """PRD 2.3 - limit defaults to 10 (1..100), offset defaults to 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit", "").strip()
        if not INT_RE.match(raw):
            _bad("limit", "must be an integer between 1 and 100")
        limit = int(raw)
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset", "").strip()
        if not INT_RE.match(raw):
            _bad("offset", "must be a non-negative integer")
        offset = int(raw)
        if offset < 0:
            _bad("offset", "must be at least 0")
    return limit, offset


def query_enum(field, choices):
    if field not in request.args:
        return None
    value = request.args.get(field)
    if value not in choices:
        _bad(field, "must be one of %s" % ", ".join(choices))
    return value


def query_str(field):
    if field not in request.args:
        return None
    return request.args.get(field)


def query_bool(field):
    if field not in request.args:
        return None
    value = request.args.get(field, "").strip().lower()
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    _bad(field, "must be true or false")


def query_int(field):
    if field not in request.args:
        return None
    raw = request.args.get(field, "").strip()
    if not INT_RE.match(raw):
        _bad(field, "must be an integer")
    return int(raw)
