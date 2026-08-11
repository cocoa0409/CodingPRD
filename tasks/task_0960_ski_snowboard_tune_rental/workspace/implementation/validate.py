"""Request body validators. All field-shape failures are ERR_INVALID_REQUEST."""

from flask import request

from errors import err
from store import is_date_str, is_time_str

GEAR_TYPES = ("SKI", "SNOWBOARD", "BOOT", "POLES")
TIERS = ("STANDARD", "PERFORMANCE", "DEMO", "JUNIOR")
SKIER_TYPES = ("TYPE_1", "TYPE_2", "TYPE_3")
PICKUP_METHODS = ("SHOP", "SLOPE_SIDE")
SERVICES = ("WAX", "EDGE_TUNE", "BASE_GRIND", "BINDING_ADJUST")
SEVERITIES = ("COSMETIC", "MINOR", "MAJOR", "TOTAL_LOSS")
PACKAGE_TIERS = ("JUNIOR_SKI", "JUNIOR_BOARD")
RESOLUTIONS = ("UPHELD", "WAIVED")
INSPECT_OUTCOMES = ("PASS", "NEEDS_TUNE", "DAMAGED")

PACKAGE_GEAR = {"JUNIOR_SKI": "SKI", "JUNIOR_BOARD": "SNOWBOARD"}


def body():
    return request.get_json(silent=True) or {}


def _bad(msg):
    raise err("ERR_INVALID_REQUEST", msg)


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        _bad("Missing or invalid required field: %s" % name)
    return v


def opt_str(b, name):
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        _bad("Invalid field: %s" % name)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, name, minimum=None):
    v = b.get(name)
    if not _is_int(v):
        _bad("Missing or invalid integer field: %s" % name)
    if minimum is not None and v < minimum:
        _bad("Field %s must be >= %d" % (name, minimum))
    return v


def opt_int(b, name, minimum=None):
    v = b.get(name)
    if v is None:
        return None
    if not _is_int(v):
        _bad("Invalid integer field: %s" % name)
    if minimum is not None and v < minimum:
        _bad("Field %s must be >= %d" % (name, minimum))
    return v


def req_num(b, name):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("Missing or invalid numeric field: %s" % name)
    return v


def req_enum(b, name, allowed):
    v = b.get(name)
    if v not in allowed:
        _bad("Missing or invalid enum field: %s" % name)
    return v


def opt_bool(b, name, default=False):
    v = b.get(name, default)
    if not isinstance(v, bool):
        _bad("Invalid boolean field: %s" % name)
    return v


def req_date(b, name):
    v = b.get(name)
    if not is_date_str(v):
        _bad("Missing or invalid date field (YYYY-MM-DD): %s" % name)
    return v


def req_time(b, name):
    v = b.get(name)
    if not is_time_str(v):
        _bad("Missing or invalid time field (HH:MM): %s" % name)
    return v


def get_or_404(collection, _id, what="Resource"):
    ent = collection.get(_id) if isinstance(_id, str) else None
    if ent is None:
        raise err("ERR_NOT_FOUND", "%s not found: %s" % (what, _id))
    return ent
