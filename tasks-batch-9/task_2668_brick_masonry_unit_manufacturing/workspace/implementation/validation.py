"""Payload well-formedness (ladder rule 7) and enumerated vocabularies (PRD 2.11)."""

import json
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_dt

MATERIAL_TYPES = ("CLAY", "SHALE")
COLOR_FAMILIES = ("RED", "BUFF", "GRAY", "BROWN")
TEXTURES = ("WIRE_CUT", "SMOOTH", "SAND_FACED", "TUMBLED")
DURABILITY_GRADES = ("SW", "MW", "NW")
FIRING_GRADES = ("ON_COLOR", "OFF_COLOR_SALVAGE", "OVERFIRE_SCRAP", "UNDERFIRE_SCRAP")
UNLOADING_EQUIPMENT = ("CUSTOMER_FORKLIFT", "TRUCK_MOUNTED_FORKLIFT", "CRANE")
BANDING_TYPES = ("STEEL", "POLY")
COMPONENT_SOURCES = ("MANUAL", "AUTO_FILL")

PLANT_STATUSES = ("ACTIVE", "IDLED")
PIT_STATUSES = ("OPEN", "SUSPENDED", "DEPLETED")
FORMULATION_STATUSES = ("DRAFT", "QUALIFIED", "RETIRED")
KILN_STATUSES = ("AVAILABLE", "MAINTENANCE")
KILN_CAR_STATUSES = ("IDLE", "SET", "IN_KILN", "OUT_OF_SERVICE")
PRODUCTION_RUN_STATUSES = ("SETTING", "SET", "HELD", "LOADED", "FIRED", "SCRAPPED")
KILN_RUN_STATUSES = ("SCHEDULED", "FIRING", "GRADED", "ABORTED")
FIRED_LOT_STATUSES = ("AVAILABLE", "RESERVED", "CONSUMED", "QUARANTINED", "SCRAP")
BLEND_STATUSES = ("DRAFT", "COMPOSED", "CERTIFIED", "RELEASED", "VOID")
BLEND_COMPONENT_STATUSES = ("ALLOCATED", "VOIDED", "CONSUMED")
PANEL_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "REVISION_REQUESTED",
    "APPROVED",
    "EXPIRED",
    "WITHDRAWN",
)
FULFILLMENT_STATUSES = (
    "DRAFT",
    "ASSIGNED",
    "IN_BLENDING",
    "PACKAGED",
    "DELIVERED",
    "CANCELLED",
)
FREIGHT_STATUSES = ("UNQUOTED", "ESTIMATED", "FINALIZED", "INVOICED", "WAIVED")


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parse the JSON request body. Decimals are preserved exactly."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError):
        raise bad("Request body must be a JSON object.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object.")
    return parsed


def _present(payload, name, required):
    if name not in payload or payload[name] is None:
        if required:
            raise bad("Field '%s' is required." % name)
        return False
    return True


def v_str(payload, name, required=True, min_len=1, max_len=None):
    if not _present(payload, name, required):
        return None
    value = payload[name]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % name)
    if len(value) < min_len:
        raise bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def v_int(payload, name, required=True, minv=None, maxv=None):
    if not _present(payload, name, required):
        return None
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, Decimal) and value == value.to_integral_value():
            value = int(value)
        else:
            raise bad("Field '%s' must be an integer." % name)
    if minv is not None and value < minv:
        raise bad("Field '%s' must be >= %s." % (name, minv))
    if maxv is not None and value > maxv:
        raise bad("Field '%s' must be <= %s." % (name, maxv))
    return int(value)


def v_num(payload, name, scale, required=True, minv=None, maxv=None):
    """A decimal with at most `scale` fractional digits, within [minv, maxv]."""
    if not _present(payload, name, required):
        return None
    value = payload[name]
    if isinstance(value, bool):
        raise bad("Field '%s' must be a number." % name)
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = Decimal(value)
    elif isinstance(value, float):
        dec = Decimal(repr(value))
    else:
        raise bad("Field '%s' must be a number." % name)
    if not dec.is_finite():
        raise bad("Field '%s' must be a finite number." % name)
    exponent = dec.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > scale:
        raise bad("Field '%s' allows at most %d decimal places." % (name, scale))
    if minv is not None and dec < Decimal(str(minv)):
        raise bad("Field '%s' must be >= %s." % (name, minv))
    if maxv is not None and dec > Decimal(str(maxv)):
        raise bad("Field '%s' must be <= %s." % (name, maxv))
    return dec


def v_enum(payload, name, allowed, required=True):
    if not _present(payload, name, required):
        return None
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def v_bool(payload, name, required=False, default=False):
    if not _present(payload, name, required):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def v_enum_array(payload, name, allowed, required=True):
    if not _present(payload, name, required):
        return None
    value = payload[name]
    if not isinstance(value, list) or len(value) == 0:
        raise bad("Field '%s' must be a non-empty array." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise bad("Field '%s' entries must be one of %s." % (name, ", ".join(allowed)))
    return list(value)


def v_datetime(payload, name, required=True):
    if not _present(payload, name, required):
        return None
    value = payload[name]
    parsed = parse_dt(value)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 UTC instant." % name)
    return parsed


def v_id(payload, name, required=True):
    if not _present(payload, name, required):
        return None
    value = payload[name]
    if not isinstance(value, str) or value == "":
        raise bad("Field '%s' must be a non-empty string id." % name)
    return value


def raw_id(payload, name):
    """Best-effort id read used before payload validation (ladder rule 5)."""
    value = payload.get(name)
    return value if isinstance(value, str) and value else None
