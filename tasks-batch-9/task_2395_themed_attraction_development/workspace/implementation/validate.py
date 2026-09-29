"""Request-body / query-parameter schema validation (PRD section 2.10 tier 3).

Every violation raises ERR_INVALID_REQUEST (400): a missing required field, an
unknown field, an enum value outside its declared members, a number outside its
declared range or decimal-place limit, a malformed datetime.
"""

import json
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import ApiError, invalid

# ------------------------------------------------------------------- enums
DESIGN_PHASES = (
    "BLUE_SKY",
    "CONCEPT",
    "SCHEMATIC",
    "DESIGN_DEVELOPMENT",
    "PRODUCTION",
    "INSTALLATION",
    "TECHNICAL_REHEARSAL",
    "SOFT_OPEN",
    "OPERATIONS_HANDOVER",
)
READINESS_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
RIDE_SYSTEM_TYPES = (
    "DARK_RIDE_TRACKLESS",
    "OMNIMOVER",
    "LAUNCH_COASTER",
    "BOAT_FLUME",
    "MOTION_BASE_THEATER",
)
RIDE_SYSTEM_STATUSES = ("CANDIDATE", "SELECTED", "ENGINEERED", "COMMISSIONED")
SAFETY_STANDARDS = ("ASTM_F2291", "EN_13814")
ROUTING_TYPES = ("STANDARD", "ACCESSIBLE", "VIRTUAL_RETURN")
QUEUE_STATUSES = ("PROPOSED", "ACCEPTED", "RETIRED")
SCENE_STATUSES = ("DRAFT", "SEQUENCED", "PROGRAMMED", "VALIDATED", "HELD")
DISCIPLINE_CHANNELS = ("LIGHTING", "AUDIO", "MEDIA", "ANIMATION", "SPECIAL_EFFECT")
CUE_STATUSES = ("PLANNED", "VERIFIED")
DISCIPLINE_SCOPES = ("SHOW_SET", "RIDE_AND_CONTROLS", "MEDIA_AND_AV", "INTEGRATED")
PACKAGE_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "SUPERSEDED")
REVIEW_STATUSES = ("IN_REVIEW", "FINDINGS_ISSUED", "CLEARED")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
FINDING_STATUSES = ("OPEN", "RESOLVED", "CLOSED", "WAIVED")
VE_STATUSES = ("PROPOSED", "UNDER_REVIEW", "ADOPTED", "REJECTED")
PARTY_ROLES = ("OwnerRep", "ContractorPM", "CreativeDirector")
DECISIONS = ("APPROVE", "ABSTAIN", "VETO")
RUN_KINDS = ("TECHNICAL_REHEARSAL", "CAST_REHEARSAL", "SOFT_OPEN")
RUN_STATUSES = ("SCHEDULED", "COMPLETED")
CRITICALITIES = ("SHOW_CRITICAL", "RUN_CRITICAL", "NON_CRITICAL")
MAINTENANCE_STATUSES = ("DRAFT", "APPROVED", "HANDED_OVER")
ENTRY_KINDS = ("COMMITMENT", "CHANGE_ORDER", "VE_SAVING", "REVERSAL")


class Field(object):
    def __init__(
        self,
        name,
        kind,
        required=True,
        nullable=False,
        min_len=None,
        max_len=None,
        minimum=None,
        maximum=None,
        exclusive_min=None,
        exclusive_max=None,
        max_dp=None,
        values=None,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.nullable = nullable
        self.min_len = min_len
        self.max_len = max_len
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_min = exclusive_min
        self.exclusive_max = exclusive_max
        self.max_dp = max_dp
        self.values = values


def S(name, min_len=1, max_len=None, required=True, nullable=False):
    return Field(name, "string", required=required, nullable=nullable, min_len=min_len, max_len=max_len)


def I(name, minimum=None, maximum=None, required=True, nullable=False):
    return Field(name, "integer", required=required, nullable=nullable, minimum=minimum, maximum=maximum)


def N(name, minimum=None, maximum=None, exclusive_min=None, exclusive_max=None, max_dp=None, required=True, nullable=False):
    return Field(
        name,
        "number",
        required=required,
        nullable=nullable,
        minimum=minimum,
        maximum=maximum,
        exclusive_min=exclusive_min,
        exclusive_max=exclusive_max,
        max_dp=max_dp,
    )


def E(name, values, required=True, nullable=False):
    return Field(name, "enum", required=required, nullable=nullable, values=values)


def DT(name, required=True, nullable=False):
    return Field(name, "datetime", required=required, nullable=nullable)


def ID(name, required=True, nullable=False):
    return Field(name, "id", required=required, nullable=nullable)


# ----------------------------------------------------------------- body access
def read_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (ValueError, UnicodeDecodeError):
        raise invalid("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise invalid("Request body must be a JSON object.")
    return parsed


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _to_decimal(value):
    if isinstance(value, Decimal):
        return value
    if _is_int(value):
        return Decimal(value)
    return None


def _decimal_places(value):
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        return 0
    return max(0, -exponent)


def _check_range(field, number):
    if field.minimum is not None and number < Decimal(str(field.minimum)):
        raise invalid("%s is below its minimum." % field.name)
    if field.maximum is not None and number > Decimal(str(field.maximum)):
        raise invalid("%s is above its maximum." % field.name)
    if field.exclusive_min is not None and number <= Decimal(str(field.exclusive_min)):
        raise invalid("%s must be strictly greater than %s." % (field.name, field.exclusive_min))
    if field.exclusive_max is not None and number >= Decimal(str(field.exclusive_max)):
        raise invalid("%s must be strictly less than %s." % (field.name, field.exclusive_max))


def _coerce(field, value):
    kind = field.kind
    if kind in ("string", "id"):
        if not isinstance(value, str):
            raise invalid("%s must be a string." % field.name)
        length = len(value)
        if field.min_len is not None and length < field.min_len:
            raise invalid("%s is shorter than %d characters." % (field.name, field.min_len))
        if field.max_len is not None and length > field.max_len:
            raise invalid("%s is longer than %d characters." % (field.name, field.max_len))
        if kind == "id" and length == 0:
            raise invalid("%s must be a non-empty string." % field.name)
        return value
    if kind == "integer":
        if not _is_int(value):
            raise invalid("%s must be an integer." % field.name)
        _check_range(field, Decimal(value))
        return value
    if kind == "number":
        number = _to_decimal(value)
        if number is None:
            raise invalid("%s must be a number." % field.name)
        try:
            number = +number
        except InvalidOperation:
            raise invalid("%s must be a number." % field.name)
        if field.max_dp is not None and _decimal_places(number) > field.max_dp:
            raise invalid("%s carries more than %d decimal places." % (field.name, field.max_dp))
        _check_range(field, number)
        return number
    if kind == "enum":
        if not isinstance(value, str) or value not in field.values:
            raise invalid("%s is not a declared enum member." % field.name)
        return value
    if kind == "datetime":
        if not isinstance(value, str) or store.parse_dt(value) is None:
            raise invalid("%s is not a valid ISO 8601 instant." % field.name)
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise invalid("%s must be a boolean." % field.name)
        return value
    raise invalid("%s has an unsupported type." % field.name)  # pragma: no cover


def validate_body(body, fields):
    """Validate `body` against `fields`; returns a dict of coerced values."""
    allowed = set()
    for field in fields:
        allowed.add(field.name)
    for key in body:
        if key not in allowed:
            raise invalid("Unknown field '%s'." % key)
    out = {}
    for field in fields:
        if field.name not in body:
            if field.required:
                raise invalid("Missing required field '%s'." % field.name)
            continue
        value = body[field.name]
        if value is None:
            if field.nullable:
                out[field.name] = None
                continue
            raise invalid("%s must not be null." % field.name)
        out[field.name] = _coerce(field, value)
    return out


# ------------------------------------------------------------ query parameters
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            raise invalid("limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            raise invalid("offset must be at least 0.")
    return limit, offset


def _query_int(name, raw):
    text = raw.strip()
    if not text:
        raise invalid("%s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise invalid("%s must be an integer." % name)
    return int(text)


def enum_filter(name, values):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in values:
        raise invalid("%s is not a declared enum member." % name)
    return raw


def string_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw
