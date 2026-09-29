"""Request-shape validation (PRD §2.9 band 2 — ERR_INVALID_REQUEST, HTTP 400)."""

from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError, ERR_INVALID_REQUEST
from numeric import dec

MISSING = object()

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
ENTITY_TYPES = ("PACKER", "PACKER_PROCESSOR", "IMPORTER")
SPECIES = ("CATTLE", "SWINE", "LAMB")
PLANT_STATUSES = ("ACTIVE", "IDLE", "CLOSED")
BASIS_VARIANTS = ("FIVE_YEAR_AVERAGE", "PRIOR_YEAR_ACTUAL")
REPORT_CLASSES = ("LIVE_ANIMAL", "BOXED_BEEF", "WHOLESALE_CUTS")
FREQUENCIES = ("DAILY", "WEEKLY")
PURCHASE_TYPES = ("NEGOTIATED", "NEGOTIATED_GRID", "FORMULA", "FORWARD_CONTRACT", "PACKER_OWNED")
PRODUCT_CLASSES = (
    "BOXED_BEEF_CHOICE_CUTOUT",
    "BOXED_BEEF_SELECT_CUTOUT",
    "GROUND_BEEF",
    "TRIMMINGS",
)
SALE_TYPES = ("NEGOTIATED", "FORMULA_NET", "DELIVERED")
CATEGORIES = ("LIVE_STEER_HEIFER", "LIVE_COW_BULL", "BOXED_BEEF_CUTOUT", "WHOLESALE_PORK_CUTS")
WEIGHTING_VARIANTS = ("HEAD_WEIGHTED", "WEIGHT_WEIGHTED")
PURCHASE_TYPE_FILTERS = ("ALL_PRICED", "NEGOTIATED_ONLY")
DECISIONS = ("ACCEPT", "REJECT")
VIOLATION_TYPES = ("LATE_FILING", "INACCURATE_DATA", "NON_REGISTRATION")
STANCES = ("SUPPORT", "OPPOSE", "NEUTRAL")


def bad(message):
    return ApiError(ERR_INVALID_REQUEST, message)


def body():
    """Parsed JSON object body; a non-object or malformed body is a shape error."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        raise bad("Request body is not valid JSON.")
    if payload is None:
        raise bad("Request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise bad("Request body must be a JSON object.")
    return payload


def present(payload, field):
    return field in payload and payload[field] is not None


def get_string(payload, field, required=True, min_len=1, max_len=None, default=None):
    if not present(payload, field):
        if required:
            raise bad("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % field)
    stripped = value.strip()
    if min_len is not None and len(stripped) < min_len:
        raise bad("Field '%s' must not be blank." % field)
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' exceeds %d characters." % (field, max_len))
    return value


def get_enum(payload, field, allowed, required=True, default=None):
    if not present(payload, field):
        if required:
            raise bad("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def get_int(payload, field, required=True, minimum=None, maximum=None, default=None):
    if not present(payload, field):
        if required:
            raise bad("Field '%s' is required." % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            raise bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def get_decimal(payload, field, required=True, minimum=None, maximum=None,
                exclusive_minimum=None, default=None):
    if not present(payload, field):
        if required:
            raise bad("Field '%s' is required." % field)
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise bad("Field '%s' must be a number." % field)
    try:
        number = dec(value)
    except (InvalidOperation, ValueError):
        raise bad("Field '%s' must be a number." % field)
    if not number.is_finite():
        raise bad("Field '%s' must be a finite number." % field)
    if exclusive_minimum is not None and number <= dec(exclusive_minimum):
        raise bad("Field '%s' must be strictly greater than %s." % (field, exclusive_minimum))
    if minimum is not None and number < dec(minimum):
        raise bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and number > dec(maximum):
        raise bad("Field '%s' must be <= %s." % (field, maximum))
    return number


def get_datetime(payload, field, required=True):
    """Returns (raw_string, datetime) so the raw client value round-trips exactly."""
    if not present(payload, field):
        if required:
            raise bad("Field '%s' is required." % field)
        return None, None
    value = payload[field]
    if not isinstance(value, str):
        raise bad("Field '%s' must be an ISO 8601 datetime string." % field)
    parsed = clock.parse_iso(value)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 datetime string." % field)
    return value, parsed


def get_head_history(payload, field, required=True, default=None):
    """annual_head_history: keys are 4-digit year strings, values non-negative ints."""
    if not present(payload, field):
        if required:
            raise bad("Field '%s' is required." % field)
        return default
    value = payload[field]
    if not isinstance(value, dict):
        raise bad("Field '%s' must be an object keyed by four-digit year strings." % field)
    normalized = {}
    for key, head in value.items():
        if not isinstance(key, str) or len(key) != 4 or not key.isdigit():
            raise bad("Field '%s' keys must be four-digit year strings." % field)
        if isinstance(head, bool) or not isinstance(head, int):
            if isinstance(head, float) and float(head).is_integer():
                head = int(head)
            else:
                raise bad("Field '%s' values must be non-negative integers." % field)
        if head < 0:
            raise bad("Field '%s' values must be non-negative integers." % field)
        normalized[key] = head
    return normalized


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("Query parameter 'limit' must be between 1 and 100.")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise bad("Query parameter '%s' must be a boolean." % name)


def query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise bad("Query parameter '%s' must be an integer." % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
