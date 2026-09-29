"""Priority 5 - request body / query well-formedness (ERR_INVALID_REQUEST)."""
import re

from flask import request

from core import ApiError, parse_date, parse_dt

BAD = "ERR_INVALID_REQUEST"

KITCHEN_TYPES = ["HOME_COTTAGE", "HOME_INSPECTED", "COMMERCIAL_SHARED"]
FOOD_CATEGORIES = ["TCS", "NON_TCS", "BAKED_NON_TCS"]
ALLERGENS = [
    "MILK",
    "EGG",
    "FISH",
    "SHELLFISH",
    "TREE_NUT",
    "PEANUT",
    "WHEAT",
    "SOY",
    "SESAME",
]
HANDOFF_MODES = ["BATCH_COOK_AND_CHILL", "SAME_DAY_HOT"]
SERVICE_MODES = ["DOOR_DELIVERY", "HUB_PICKUP"]
DOC_TYPES = ["FOOD_HANDLER_CERT", "KITCHEN_INSPECTION"]
SUBJECT_TYPES = ["COOK", "MENU_ITEM", "ORDER"]
INCIDENT_CATEGORIES = [
    "ALLERGEN_MISLABEL",
    "FOODBORNE_ILLNESS",
    "TEMP_ABUSE",
    "FOREIGN_OBJECT",
    "LABEL_MISSING",
]
SEVERITIES = ["MINOR", "MODERATE", "SEVERE", "CRITICAL"]
PAYOUT_BASES = ["ACCRUAL_WINDOW", "CASH_HANDOFF"]
REFUND_REASONS = [
    "SAFETY",
    "QUALITY",
    "LATE",
    "COOK_CANCELLED",
    "PLATFORM_ERROR",
    "WINDOW_CANCELLED",
]
FAULT_PARTIES = ["COOK", "PLATFORM", "SHARED"]
CANCELLED_REASONS = ["NO_APPROVED_MENU", "COOK_REQUEST"]

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")
POSTAL_RE = re.compile(r"^[0-9]{5}$")


def body():
    """Parse the JSON body. A completely absent body is treated as {}."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError(BAD, "request body must be a JSON object")
    return data


def present(data, key):
    return key in data and data[key] is not None


def req(data, key):
    if not present(data, key):
        raise ApiError(BAD, "%s is required" % key)
    return data[key]


def s_str(data, key, min_len=1, max_len=None, required=True):
    if not present(data, key):
        if required:
            raise ApiError(BAD, "%s is required" % key)
        return None
    value = data[key]
    if not isinstance(value, str):
        raise ApiError(BAD, "%s must be a string" % key)
    if len(value) < min_len:
        raise ApiError(BAD, "%s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise ApiError(BAD, "%s must be at most %d characters" % (key, max_len))
    return value


def s_int(data, key, minimum=None, maximum=None, required=True, error=BAD):
    if not present(data, key):
        if required:
            raise ApiError(BAD, "%s is required" % key)
        return None
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(BAD, "%s must be an integer" % key)
    if minimum is not None and value < minimum:
        raise ApiError(error, "%s must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        raise ApiError(error, "%s must be <= %s" % (key, maximum))
    return value


def s_bool(data, key, required=True, default=None):
    if not present(data, key):
        if required:
            raise ApiError(BAD, "%s is required" % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ApiError(BAD, "%s must be a boolean" % key)
    return value


def s_enum(data, key, members, required=True):
    if not present(data, key):
        if required:
            raise ApiError(BAD, "%s is required" % key)
        return None
    value = data[key]
    if not isinstance(value, str) or value not in members:
        raise ApiError(BAD, "%s must be one of %s" % (key, ", ".join(members)))
    return value


def s_id(data, key, required=True):
    if not present(data, key):
        if required:
            raise ApiError(BAD, "%s is required" % key)
        return None
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise ApiError(BAD, "%s must be a non-empty string identifier" % key)
    return value


def s_dt(data, key, required=True):
    """Returns (raw_string, datetime)."""
    if not present(data, key):
        if required:
            raise ApiError(BAD, "%s is required" % key)
        return None, None
    value = data[key]
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        raise ApiError(BAD, "%s must be an ISO 8601 UTC timestamp" % key)
    return value, parsed


def s_date(data, key, required=True):
    """Returns (raw_string, date)."""
    if not present(data, key):
        if required:
            raise ApiError(BAD, "%s is required" % key)
        return None, None
    value = data[key]
    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is None or not isinstance(value, str) or len(value.strip()) != 10:
        raise ApiError(BAD, "%s must be an ISO 8601 calendar date" % key)
    return value, parsed


def s_str_list(data, key, required=True, allow_empty=False, pattern=None):
    if not present(data, key):
        if required:
            raise ApiError(BAD, "%s is required" % key)
        return None
    value = data[key]
    if not isinstance(value, list):
        raise ApiError(BAD, "%s must be an array" % key)
    if not allow_empty and len(value) == 0:
        raise ApiError(BAD, "%s must not be empty" % key)
    for item in value:
        if not isinstance(item, str) or not item:
            raise ApiError(BAD, "%s must contain non-empty strings" % key)
        if pattern is not None and not pattern.match(item):
            raise ApiError(BAD, "%s contains an invalid entry: %s" % (key, item))
    return value


def s_enum_list(data, key, members, required=True, allow_empty=False):
    value = s_str_list(data, key, required=required, allow_empty=allow_empty)
    if value is None:
        return None
    for item in value:
        if item not in members:
            raise ApiError(BAD, "%s must be a subset of %s" % (key, ", ".join(members)))
    return value


# ------------------------------------------------------------------- pagination
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not re.match(r"^-?[0-9]+$", raw.strip()):
        raise ApiError(BAD, "%s must be an integer" % name)
    value = int(raw.strip())
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError(BAD, "%s is out of range" % name)
    return value


def pagination():
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def filters(*names):
    out = {}
    for name in names:
        raw = request.args.get(name)
        if raw is not None and raw != "":
            out[name] = raw
    return out
