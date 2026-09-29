"""Auth, request-shape validation and query parsing (PRD 2.1, 2.3, 2.9 rules 1-3)."""

import datetime
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

UTC = datetime.timezone.utc

ROLES = ("ProgramAdmin", "FieldOfficer", "Grower", "ConditioningManager",
         "CertificationAgency", "SettlementAccountant")

CROP_KINDS = ("WHEAT", "TRITICALE", "SOYBEAN", "SUNFLOWER", "ALFALFA", "CANOLA")
SEED_CLASSES = ("FOUNDATION", "REGISTERED", "CERTIFIED")
CONTRACT_CLASSES = ("FOUNDATION", "REGISTERED", "CERTIFIED", "COMMERCIAL_INCREASE")
SIGNAL_WORDS = ("CAUTION", "WARNING", "DANGER")
EQUIPMENT_KINDS = ("COMBINE", "TRUCK", "AUGER")
STAGES = ("CLEANING", "SIZING", "TREATING", "BAGGING")
SAMPLE_KINDS = ("INITIAL", "RETEST")


def bad_request(detail):
    raise ApiError("ERR_INVALID_REQUEST", detail)


# ---- authentication / authorization -------------------------------------
def authenticate(allowed_roles):
    """Rule 1 then rule 2 of the ladder; runs before any payload parsing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# ---- scalar coercion ----------------------------------------------------
def _is_bool(value):
    return isinstance(value, bool)


def check_string(name, value):
    if not isinstance(value, str):
        bad_request("Field '%s' must be a string." % name)
    return value


def check_integer(name, value):
    if _is_bool(value) or not isinstance(value, int):
        bad_request("Field '%s' must be an integer." % name)
    return value


def check_number(name, value):
    if _is_bool(value) or not isinstance(value, (int, float)):
        bad_request("Field '%s' must be a number." % name)
    return value


def check_boolean(name, value):
    if not _is_bool(value):
        bad_request("Field '%s' must be a boolean." % name)
    return value


def check_enum(name, value, members):
    if not isinstance(value, str) or value not in members:
        bad_request("Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def parse_date(name, value):
    """ISO 8601 calendar date input; a full instant is accepted and truncated."""
    if not isinstance(value, str):
        bad_request("Field '%s' must be an ISO 8601 date string." % name)
    text = value.strip()
    try:
        if len(text) == 10:
            return datetime.date.fromisoformat(text)
        return parse_datetime(name, text).date()
    except ApiError:
        raise
    except Exception:
        bad_request("Field '%s' is not a valid ISO 8601 date." % name)


def parse_datetime(name, value):
    """ISO 8601 instant; a trailing Z or an explicit offset are both accepted."""
    if not isinstance(value, str):
        bad_request("Field '%s' must be an ISO 8601 timestamp string." % name)
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.datetime.fromisoformat(candidate)
    except Exception:
        try:
            parsed = datetime.datetime.combine(
                datetime.date.fromisoformat(text), datetime.time(0, 0, 0))
        except Exception:
            bad_request("Field '%s' is not a valid ISO 8601 timestamp." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


# ---- body parsing -------------------------------------------------------
def json_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        bad_request("Request body must be a JSON object.")
    if not isinstance(body, dict):
        bad_request("Request body must be a JSON object.")
    return body


class Field(object):
    def __init__(self, name, kind, required=True, members=None, minimum=None,
                 maximum=None, exclusive_min=None, default=None, nullable=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.members = members
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_min = exclusive_min
        self.default = default
        self.nullable = nullable


def parse_fields(body, fields):
    """Validate declared inputs: presence, JSON type, enum membership and
    single-field numeric ranges (ladder rule 3)."""
    out = {}
    for f in fields:
        present = f.name in body and body[f.name] is not None
        if not present:
            if f.required:
                bad_request("Field '%s' is required." % f.name)
            out[f.name] = f.default
            continue
        raw = body[f.name]
        kind = f.kind
        if kind == "string":
            value = check_string(f.name, raw)
        elif kind == "integer":
            value = check_integer(f.name, raw)
        elif kind == "number":
            value = check_number(f.name, raw)
        elif kind == "boolean":
            value = check_boolean(f.name, raw)
        elif kind == "enum":
            value = check_enum(f.name, raw, f.members)
        elif kind == "enum_array":
            if not isinstance(raw, list):
                bad_request("Field '%s' must be an array." % f.name)
            for item in raw:
                check_enum(f.name, item, f.members)
            value = list(raw)
        elif kind == "date":
            value = parse_date(f.name, raw)
        elif kind == "datetime":
            value = parse_datetime(f.name, raw)
        else:
            raise AssertionError("unknown kind " + kind)

        if kind in ("integer", "number"):
            num = Decimal(str(value))
            if f.exclusive_min is not None and num <= Decimal(str(f.exclusive_min)):
                bad_request("Field '%s' must be greater than %s." % (f.name, f.exclusive_min))
            if f.minimum is not None and num < Decimal(str(f.minimum)):
                bad_request("Field '%s' must be at least %s." % (f.name, f.minimum))
            if f.maximum is not None and num > Decimal(str(f.maximum)):
                bad_request("Field '%s' must be at most %s." % (f.name, f.maximum))
        out[f.name] = value
        if kind in ("date", "datetime"):
            out[f.name + "__raw"] = raw if isinstance(raw, str) else str(raw)
    return out


# ---- query parsing ------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad_request("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad_request("Query parameter 'offset' must not be negative.")
    return limit, offset


def query_enum(name, members):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in members:
        bad_request("Query parameter '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def query_string(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_integer(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        bad_request("Query parameter '%s' must be an integer." % name)


def query_boolean(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad_request("Query parameter '%s' must be a boolean." % name)
