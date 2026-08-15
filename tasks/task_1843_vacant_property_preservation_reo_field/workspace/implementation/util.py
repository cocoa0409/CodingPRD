"""Validation helpers, date/datetime parsing, decimal rounding, pagination."""

from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import raise_err

# ---- enum domains -----------------------------------------------------------

INVESTOR_TYPES = {"FHA", "FNMA", "FHLMC", "PRIVATE"}
ITEM_CODES = {
    "INSPECTION", "LOCK_CHANGE", "WINTERIZATION", "DEWINTERIZATION",
    "GRASS_CUT", "SNOW_REMOVAL", "DEBRIS_REMOVAL", "CODE_CURE",
    "BOARD_UP", "PERSONAL_PROPERTY", "DAMAGE_REPAIR",
}
ORDER_TYPES = {
    "INSPECTION", "SECURING", "WINTERIZATION", "DEWINTERIZATION",
    "GRASS_CUT", "SNOW_REMOVAL", "DEBRIS_REMOVAL", "CODE_CURE",
    "BOARD_UP", "PERSONAL_PROPERTY", "DAMAGE_REPAIR",
}
HEATING_SYSTEMS = {"NONE", "FORCED_AIR", "HOT_WATER", "STEAM"}
OCCUPANCY_DETERMINATIONS = {"VACANT", "OCCUPIED", "INDETERMINATE"}
VERIFIED_OCCUPANCY = {"VACANT", "OCCUPIED"}
SERVICE_TYPES = {"GRASS_CUT", "SNOW_REMOVAL"}
VIOLATION_CLASSES = {"MINOR", "MAJOR", "HAZARDOUS"}
DAMAGE_TYPES = {"VANDALISM", "THEFT", "WATER", "FIRE", "STORM", "SQUATTER", "OTHER"}
SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}
PHOTO_CATEGORIES = {
    "BEFORE", "DURING", "AFTER", "SERIAL_NUMBER",
    "DAMAGE_CLOSEUP", "STREET_SCENE", "DOCUMENT",
}
DISPOSITION_OUTCOMES = {"DISPOSED", "DONATED", "RETURNED"}
DAMAGE_CLOSE_OUTCOMES = {"CLOSED", "MONITORING"}

# order_type -> allowable item_code mapping
ORDER_ITEM_MAP = {
    "INSPECTION": "INSPECTION",
    "SECURING": "LOCK_CHANGE",
    "WINTERIZATION": "WINTERIZATION",
    "DEWINTERIZATION": "DEWINTERIZATION",
    "GRASS_CUT": "GRASS_CUT",
    "SNOW_REMOVAL": "SNOW_REMOVAL",
    "DEBRIS_REMOVAL": "DEBRIS_REMOVAL",
    "CODE_CURE": "CODE_CURE",
    "BOARD_UP": "BOARD_UP",
    "PERSONAL_PROPERTY": "PERSONAL_PROPERTY",
    "DAMAGE_REPAIR": "DAMAGE_REPAIR",
}

OCCUPANCY_GATED_ORDER_TYPES = {
    "SECURING", "WINTERIZATION", "DEWINTERIZATION", "PERSONAL_PROPERTY", "DEBRIS_REMOVAL",
}


# ---- rounding ----------------------------------------------------------------

def round_half_up_cents(value):
    """Round a Decimal to whole cents, half up; returns int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- body + field validators -------------------------------------------------

def get_body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return b


def _missing(name):
    raise_err("ERR_INVALID_REQUEST", f"Missing required field: {name}")


def req_str(b, name):
    v = b.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return v


def opt_str(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, str):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return v


def req_int(b, name):
    v = b.get(name)
    if v is None:
        _missing(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    return v


def req_amount(b, name):
    v = req_int(b, name)
    if v < 0:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be at least 0")
    return v


def opt_amount(b, name):
    v = b.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if v < 0:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be at least 0")
    return v


def req_quantity(b, name):
    v = req_int(b, name)
    if v < 1:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be at least 1")
    return v


def req_bool(b, name):
    v = b.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, bool):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


def opt_bool(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


def req_enum(b, name, domain):
    v = req_str(b, name)
    if v not in domain:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(domain)}")
    return v


def opt_enum(b, name, domain, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, str) or v not in domain:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be one of {sorted(domain)}")
    return v


def parse_date_str(s, name):
    if not isinstance(s, str):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO date string")
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO date string")


def req_date(b, name):
    v = b.get(name)
    if v is None:
        _missing(name)
    return parse_date_str(v, name).isoformat()


def opt_date(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    return parse_date_str(v, name).isoformat()


def parse_datetime_str(s, name):
    if not isinstance(s, str):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO 8601 datetime string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except (ValueError, TypeError):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(b, name):
    v = b.get(name)
    if v is None:
        _missing(name)
    return parse_datetime_str(v, name)


def req_md(b, name):
    v = req_str(b, name)
    parts = v.split("-")
    if len(parts) != 2:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an MM-DD string")
    try:
        month = int(parts[0])
        day = int(parts[1])
        date(2000, month, day)
    except (ValueError, TypeError):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an MM-DD string")
    if len(parts[0]) != 2 or len(parts[1]) != 2:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an MM-DD string")
    return v


def opt_str_list(b, name, default=None):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an array of strings")
    return v


# ---- existence / lookup --------------------------------------------------------

def get_or_404(table, entity_id, label):
    e = table.get(entity_id)
    if e is None:
        raise_err("ERR_NOT_FOUND", f"{label} not found: {entity_id}")
    return e


# ---- pagination -----------------------------------------------------------------

def parse_pagination():
    try:
        limit = int(request.args.get("limit", "10"))
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(request.args.get("offset", "0"))
    except (ValueError, TypeError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, serializer, limit, offset):
    """items: full filtered list (already sorted). Returns (page, total)."""
    total = len(items)
    page = items[offset:offset + limit]
    return [serializer(e) for e in page], total


def sort_created(items):
    """created_at ASC; stable on insertion sequence for ties."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
