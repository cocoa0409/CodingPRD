"""Band 4 of PRD §2.5 — request-shape validation, and the enumerations of §2.12.

Every helper here raises ``ERR_INVALID_REQUEST`` (400). Shape validation always
runs before any body-borne foreign key is resolved, so a request that both
omits a required field and names a non-existent parent answers 400.
"""

from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ERR_INVALID_REQUEST, fail

# ---------------------------------------------------------------------------
# §2.12 enumerations of record
# ---------------------------------------------------------------------------
CATEGORIES = ("BEVERAGE", "SNACK", "DAIRY", "HOUSEHOLD")
PROJECT_TYPES = ("NEW_BRAND", "LINE_EXTENSION", "RENOVATION")
FUNCTIONS = ("R_AND_D", "MARKETING", "FINANCE", "OPERATIONS", "QUALITY",
             "REGULATORY", "SALES")
VOTES = ("APPROVE", "APPROVE_WITH_CONDITIONS", "REJECT")
CHANNELS = ("GROCERY", "MASS", "CLUB", "CONVENIENCE", "ECOMMERCE")
TEST_TYPES = ("MONADIC", "SEQUENTIAL_MONADIC", "IN_HOME_USE")
VARIANT_MODES = ("BOTTOM_UP", "TOP_DOWN")
CASE_TYPES = ("PRELIMINARY", "FINAL")
ALLERGEN_REGIMES = ("NONE", "DAIRY", "NUT", "GLUTEN")
ATTAINMENT_BASES = ("CUMULATIVE", "TRAILING")
POST_LAUNCH_DECISIONS = ("CONTINUE", "FIX", "DISCONTINUE")
SCREENING_DECISIONS = ("PENDING", "PASSED", "REJECTED")
STABILITY_VERDICTS = ("PASS", "FAIL")

DEV_STATES = ("IDEA", "SCREENED", "PILOT_QUALIFIED", "LAUNCH_READY", "LAUNCHED",
              "IN_MARKET_FIX", "KILLED", "DISCONTINUED")
COMMERCIAL_STATES = ("NOT_STARTED", "SELL_IN_SCHEDULED", "PRESENTED", "AUTHORIZED",
                     "SELL_IN_REJECTED", "LAUNCH_LOCKED", "LOCK_SLIPPED", "SHIPPED")
STAGE_FROM = ("SCREENED", "PILOT_QUALIFIED")
STAGE_TO = ("PILOT_QUALIFIED", "LAUNCH_READY")

DELIVERABLE_TYPES = (
    "CONSUMER_CONCEPT_TEST", "PRELIM_BUSINESS_CASE", "FINAL_BUSINESS_CASE",
    "PILOT_SCALE_UP_REPORT", "SHELF_LIFE_REPORT", "REGULATORY_CLEARANCE",
    "MANUFACTURING_READINESS", "DISTRIBUTION_READINESS", "MARKETING_LAUNCH_PLAN",
    "SALES_SELL_IN_PLAN",
)
EVIDENCE_TYPES = DELIVERABLE_TYPES[:6]
READINESS_TYPES = DELIVERABLE_TYPES[6:]

DELIVERABLE_OWNER_MAP = {
    "CONSUMER_CONCEPT_TEST": "MARKETING",
    "PRELIM_BUSINESS_CASE": "FINANCE",
    "FINAL_BUSINESS_CASE": "FINANCE",
    "PILOT_SCALE_UP_REPORT": "R_AND_D",
    "SHELF_LIFE_REPORT": "QUALITY",
    "REGULATORY_CLEARANCE": "REGULATORY",
    "MANUFACTURING_READINESS": "OPERATIONS",
    "DISTRIBUTION_READINESS": "OPERATIONS",
    "MARKETING_LAUNCH_PLAN": "MARKETING",
    "SALES_SELL_IN_PLAN": "SALES",
}

AUTO_EVIDENCE_URL = "system://auto-approved"


# ---------------------------------------------------------------------------
# body access
# ---------------------------------------------------------------------------
def body():
    """The parsed JSON object body; an absent body counts as ``{}``."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail(ERR_INVALID_REQUEST, "Request body must be valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


def _missing(name):
    fail(ERR_INVALID_REQUEST, "Field '%s' is required." % name)


# ---------------------------------------------------------------------------
# scalars
# ---------------------------------------------------------------------------
def string_field(data, name, required=True, min_len=1, max_len=None, default=None):
    if not _present(data, name):
        if required:
            _missing(name)
        return default
    value = data[name]
    if not isinstance(value, str):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be at least %d characters."
             % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail(ERR_INVALID_REQUEST, "Field '%s' may be at most %d characters."
             % (name, max_len))
    return value


def enum_field(data, name, allowed, required=True, default=None):
    if not _present(data, name):
        if required:
            _missing(name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail(ERR_INVALID_REQUEST,
             "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def int_field(data, name, required=True, minimum=None, maximum=None, default=None):
    if not _present(data, name):
        if required:
            _missing(name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail(ERR_INVALID_REQUEST, "Field '%s' may not be below %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail(ERR_INVALID_REQUEST, "Field '%s' may not exceed %s." % (name, maximum))
    return value


def number_field(data, name, required=True, minimum=None, maximum=None,
                 places=2, default=None):
    """A JSON number, normalised to a ``Decimal`` at the field's declared scale."""
    if not _present(data, name):
        if required:
            _missing(name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a number." % name)
    if not dec.is_finite():
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a finite number." % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        fail(ERR_INVALID_REQUEST, "Field '%s' may not be below %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        fail(ERR_INVALID_REQUEST, "Field '%s' may not exceed %s." % (name, maximum))
    from calc import rhu
    return rhu(dec, places)


def datetime_field(data, name, required=True):
    """Returns ``(raw_string, datetime)`` — the raw form is echoed verbatim."""
    if not _present(data, name):
        if required:
            _missing(name)
        return None, None
    value = data[name]
    parsed = clock.parse_iso(value)
    if parsed is None:
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an ISO 8601 datetime." % name)
    return value, parsed


def id_field(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            _missing(name)
        return default
    value = data[name]
    if not isinstance(value, str) or value == "":
        fail(ERR_INVALID_REQUEST, "Field '%s' must be a non-empty string." % name)
    return value


def enum_array_field(data, name, allowed, required=True, unique=False,
                     allow_empty=True, default=None):
    if not _present(data, name):
        if required:
            _missing(name)
        return list(default) if default is not None else None
    value = data[name]
    if not isinstance(value, list):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an array." % name)
    if not allow_empty and not value:
        fail(ERR_INVALID_REQUEST, "Field '%s' may not be empty." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail(ERR_INVALID_REQUEST,
                 "Field '%s' entries must be one of %s." % (name, ", ".join(allowed)))
    if unique and len(set(value)) != len(value):
        fail(ERR_INVALID_REQUEST, "Field '%s' may not contain duplicates." % name)
    return list(value)


def string_array_field(data, name, required=True, min_items=None, max_items=None,
                       default=None):
    if not _present(data, name):
        if required:
            _missing(name)
        return list(default) if default is not None else None
    value = data[name]
    if not isinstance(value, list):
        fail(ERR_INVALID_REQUEST, "Field '%s' must be an array." % name)
    if min_items is not None and len(value) < min_items:
        fail(ERR_INVALID_REQUEST,
             "Field '%s' must hold at least %d entries." % (name, min_items))
    if max_items is not None and len(value) > max_items:
        fail(ERR_INVALID_REQUEST,
             "Field '%s' may hold at most %d entries." % (name, max_items))
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            fail(ERR_INVALID_REQUEST,
                 "Field '%s' entries must be non-empty strings." % name)
    return list(value)
