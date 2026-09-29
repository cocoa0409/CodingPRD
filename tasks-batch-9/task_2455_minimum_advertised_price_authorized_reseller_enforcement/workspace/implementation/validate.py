"""Request-shape validation helpers (PRD §2.9 step 3 -> ERR_VALIDATION 400)."""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from store import parse_iso

CHANNELS = ["MARKETPLACE", "RETAILER_SITE", "OWN_WEBSITE", "PHYSICAL_RETAIL"]
CHANNEL_SCOPES = ["ALL"] + CHANNELS
QUALITY_OBLIGATIONS = [
    "AUTHENTICITY_LABELING",
    "WARRANTY_HONORED",
    "PACKAGING_INTACT",
    "AUTHORIZED_SERVICE_ONLY",
]
LIFECYCLE_STATUSES = ["ACTIVE", "CLEARANCE", "DISCONTINUED"]
DELIVERY_CHANNELS = ["EMAIL", "CERTIFIED_MAIL", "PORTAL"]
RUNGS = ["WARNING", "SUSPENSION", "TERMINATION"]
EXCEPTION_TYPES = ["CLEARANCE", "BUNDLE", "PROMOTIONAL_EVENT"]
DEALER_INPUT_SOURCES = [
    "NONE",
    "RESELLER_PRICING_REQUEST",
    "RETAILER_INVENTORY_REPORT",
    "BRAND_MARKETING_PLAN",
]
SUPPLY_STATUSES = ["OPEN", "HOLD", "CUT_OFF"]
HOLD_REASONS = [
    "NONE",
    "PENDING_AUTHORIZATION",
    "QUALITY_OBLIGATION",
    "SUSPENSION",
    "AGREEMENT_EXPIRED",
    "TERMINATION",
]
EXPOSURE_VARIANTS = ["TRACE_ATTRIBUTED", "LOT_PRORATED"]

_HEX64 = re.compile(r"^[0-9a-f]{64}$")

_MISSING = object()


def body():
    """The JSON request body as a dict (an absent body is treated as empty)."""
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            fail("ERR_VALIDATION", "Request body must be a JSON object.")
        return {}
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def has(b, name):
    return name in b


def _bad(name, detail):
    fail("ERR_VALIDATION", "%s %s" % (name, detail))


def req_str(b, name, min_len=1, max_len=None):
    if name not in b or b[name] is None:
        _bad(name, "is required.")
    return _as_str(b[name], name, min_len, max_len)


def opt_str(b, name, min_len=1, max_len=None, default=None):
    if name not in b or b[name] is None:
        return default
    return _as_str(b[name], name, min_len, max_len)


def _as_str(value, name, min_len, max_len):
    if not isinstance(value, str):
        _bad(name, "must be a string.")
    if min_len is not None and len(value) < min_len:
        _bad(name, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters." % max_len)
    return value


def req_int(b, name, minimum=None, maximum=None):
    if name not in b or b[name] is None:
        _bad(name, "is required.")
    return _as_int(b[name], name, minimum, maximum)


def opt_int(b, name, minimum=None, maximum=None, default=None):
    if name not in b or b[name] is None:
        return default
    return _as_int(b[name], name, minimum, maximum)


def _as_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer.")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s." % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s." % maximum)
    return value


def opt_fraction(b, name, minimum, maximum, default=None, decimals=2):
    """Two-decimal fraction inputs (PRD §2.5)."""
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number.")
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        _bad(name, "must be a number.")
    if dec < Decimal(str(minimum)) or dec > Decimal(str(maximum)):
        _bad(name, "must be between %s and %s." % (minimum, maximum))
    exponent = dec.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -decimals:
        _bad(name, "must carry at most %d decimal places." % decimals)
    return float(dec)


def req_enum(b, name, allowed):
    if name not in b or b[name] is None:
        _bad(name, "is required.")
    value = b[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s." % ", ".join(allowed))
    return value


def opt_enum(b, name, allowed, default=None):
    if name not in b or b[name] is None:
        return default
    value = b[name]
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s." % ", ".join(allowed))
    return value


def req_bool(b, name):
    if name not in b or b[name] is None:
        _bad(name, "is required.")
    if not isinstance(b[name], bool):
        _bad(name, "must be a boolean.")
    return b[name]


def opt_bool(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    if not isinstance(b[name], bool):
        _bad(name, "must be a boolean.")
    return b[name]


def req_dt(b, name):
    raw = req_str(b, name)
    if parse_iso(raw) is None:
        _bad(name, "must be an ISO 8601 UTC instant.")
    return raw


def opt_dt(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    raw = _as_str(b[name], name, 1, None)
    if parse_iso(raw) is None:
        _bad(name, "must be an ISO 8601 UTC instant.")
    return raw


def req_hash(b, name):
    value = req_str(b, name)
    if not _HEX64.match(value):
        _bad(name, "must be exactly 64 lowercase hexadecimal characters.")
    return value


def req_enum_list(b, name, allowed, min_len, max_len):
    if name not in b or b[name] is None:
        _bad(name, "is required.")
    value = b[name]
    if not isinstance(value, list):
        _bad(name, "must be an array.")
    if len(value) < min_len or len(value) > max_len:
        _bad(name, "must contain between %d and %d members." % (min_len, max_len))
    for member in value:
        if not isinstance(member, str) or member not in allowed:
            _bad(name, "members must be drawn from %s." % ", ".join(allowed))
    if len(set(value)) != len(value):
        _bad(name, "members must be distinct.")
    return value


def req_bundle_components(b, name):
    value = b.get(name)
    if value is None:
        _bad(name, "is required when is_bundle is true.")
    if not isinstance(value, list):
        _bad(name, "must be an array.")
    if len(value) < 2:
        _bad(name, "must contain at least two components.")
    skus = []
    normalized = []
    for member in value:
        if not isinstance(member, dict):
            _bad(name, "members must be objects carrying sku and msrp_cents.")
        sku = member.get("sku")
        msrp = member.get("msrp_cents")
        if not isinstance(sku, str) or not sku:
            _bad(name, "members must carry a non-empty sku string.")
        if isinstance(msrp, bool) or not isinstance(msrp, int) or msrp <= 0:
            _bad(name, "members must carry an msrp_cents integer greater than zero.")
        skus.append(sku)
        normalized.append({"sku": sku, "msrp_cents": msrp})
    if len(set(skus)) != len(skus):
        _bad(name, "members must be distinct.")
    return normalized


def query_bool(name, default=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_VALIDATION", "%s must be a boolean." % name)


def query_dt(name, default=None):
    raw = request.args.get(name)
    if raw is None:
        return default
    if parse_iso(raw) is None:
        fail("ERR_VALIDATION", "%s must be an ISO 8601 UTC instant." % name)
    return raw


def query_enum(name, allowed, required=False, default=None):
    raw = request.args.get(name)
    if raw is None:
        if required:
            fail("ERR_VALIDATION", "%s is required." % name)
        return default
    if raw not in allowed:
        fail("ERR_VALIDATION", "%s must be one of %s." % (name, ", ".join(allowed)))
    return raw
