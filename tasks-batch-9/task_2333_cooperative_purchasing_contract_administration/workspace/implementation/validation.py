"""Ladder step 3: request-schema conformance (ERR_INVALID_REQUEST, 400)."""

from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_dt
from errors import fail

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def bad(detail):
    fail("ERR_INVALID_REQUEST", detail)


def json_body(allowed=(), required=()):
    """Parse the JSON body, rejecting unknown and missing-required fields."""
    if request.data:
        body = request.get_json(silent=True)
        if body is None:
            bad("request body is not valid JSON")
    else:
        body = {}
    if body is None:
        body = {}
    if not isinstance(body, dict):
        bad("request body must be a JSON object")
    for key in body.keys():
        if key not in allowed:
            bad("unknown field '%s'" % key)
    for key in required:
        if key not in body or body[key] is None:
            bad("field '%s' is required" % key)
    return body


def present(body, key):
    return key in body and body[key] is not None


# --------------------------------------------------------------------------
# scalar readers
# --------------------------------------------------------------------------

def read_str(body, key, required=False, min_len=None, max_len=None,
             enum=None, default=None):
    if not present(body, key):
        if required:
            bad("field '%s' is required" % key)
        return default
    value = body[key]
    if not isinstance(value, str):
        bad("field '%s' must be a string" % key)
    if min_len is not None and len(value) < min_len:
        bad("field '%s' is shorter than %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("field '%s' is longer than %d characters" % (key, max_len))
    if enum is not None and value not in enum:
        bad("field '%s' must be one of %s" % (key, ", ".join(enum)))
    return value


def read_int(body, key, required=False, minimum=None, maximum=None, default=None):
    if not present(body, key):
        if required:
            bad("field '%s' is required" % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("field '%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        bad("field '%s' must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("field '%s' must be <= %s" % (key, maximum))
    return value


def read_dec(body, key, required=False, minimum=None, maximum=None, default=None):
    """Read a JSON number as an exact Decimal."""
    if not present(body, key):
        if required:
            bad("field '%s' is required" % key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("field '%s' must be a number" % key)
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        bad("field '%s' must be a number" % key)
    if minimum is not None and parsed < Decimal(str(minimum)):
        bad("field '%s' must be >= %s" % (key, minimum))
    if maximum is not None and parsed > Decimal(str(maximum)):
        bad("field '%s' must be <= %s" % (key, maximum))
    return parsed


def read_bool(body, key, required=False, default=None):
    if not present(body, key):
        if required:
            bad("field '%s' is required" % key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        bad("field '%s' must be a boolean" % key)
    return value


def read_dt(body, key, required=False, default=None):
    """Read an ISO 8601 datetime; returns (raw_string, datetime)."""
    if not present(body, key):
        if required:
            bad("field '%s' is required" % key)
        return default, None
    value = body[key]
    if not isinstance(value, str):
        bad("field '%s' must be an ISO 8601 datetime string" % key)
    parsed = parse_dt(value)
    if parsed is None:
        bad("field '%s' must be an ISO 8601 datetime string" % key)
    return value, parsed


def read_list(body, key, required=False, default=None):
    if not present(body, key):
        if required:
            bad("field '%s' is required" % key)
        return default
    value = body[key]
    if not isinstance(value, list):
        bad("field '%s' must be an array" % key)
    return value


def read_id(body, key, required=False, default=None):
    if not present(body, key):
        if required:
            bad("field '%s' is required" % key)
        return default
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        bad("field '%s' must be an identifier string" % key)
    return value


def read_state_code(body, key, required=False, default=None):
    value = read_str(body, key, required=required, default=default)
    if value is None:
        return None
    check_state_code(value, key)
    return value


def check_state_code(value, key):
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        bad("field '%s' must be a two-letter uppercase state code" % key)


# --------------------------------------------------------------------------
# structured readers
# --------------------------------------------------------------------------

ADD_ON_CODES = ("FREIGHT", "INSIDE_DELIVERY", "TRAINING", "INSTALLATION")
UNITS_OF_MEASURE = ("EACH", "CASE", "PALLET", "HOUR")


def read_discount_tiers(body, key="discount_tiers", required=True):
    """1..5 well-formed tiers, ascending index from 0 and ascending thresholds."""
    raw = read_list(body, key, required=required)
    if raw is None:
        return None
    if len(raw) < 1 or len(raw) > 5:
        bad("field '%s' must contain between 1 and 5 entries" % key)
    tiers = []
    previous_threshold = None
    for position, entry in enumerate(raw):
        if not isinstance(entry, dict):
            bad("each '%s' entry must be an object" % key)
        for field in entry.keys():
            if field not in ("tier_index", "min_annual_spend_cents", "discount_pct"):
                bad("unknown field '%s' in %s entry" % (field, key))
        index = read_int(entry, "tier_index", required=True, minimum=0)
        threshold = read_int(entry, "min_annual_spend_cents", required=True, minimum=0)
        pct = read_dec(entry, "discount_pct", required=True,
                       minimum="0.0000", maximum="0.2000")
        if index != position:
            bad("'%s' tier_index values must ascend from 0" % key)
        if position == 0 and threshold != 0:
            bad("the first '%s' entry must have min_annual_spend_cents 0" % key)
        if previous_threshold is not None and threshold <= previous_threshold:
            bad("'%s' min_annual_spend_cents values must strictly ascend" % key)
        previous_threshold = threshold
        tiers.append({
            "tier_index": index,
            "min_annual_spend_cents": threshold,
            "discount_pct": pct,
        })
    return tiers


def read_add_ons(body, key="permitted_add_ons", required=False):
    """0..4 entries with unique known codes."""
    raw = read_list(body, key, required=required, default=None)
    if raw is None:
        return []
    if len(raw) > 4:
        bad("field '%s' may contain at most 4 entries" % key)
    seen = set()
    add_ons = []
    for entry in raw:
        if not isinstance(entry, dict):
            bad("each '%s' entry must be an object" % key)
        for field in entry.keys():
            if field not in ("code", "rate_pct", "cap_cents"):
                bad("unknown field '%s' in %s entry" % (field, key))
        code = read_str(entry, "code", required=True, enum=ADD_ON_CODES)
        rate = read_dec(entry, "rate_pct", required=True,
                        minimum="0.0000", maximum="0.2000")
        cap = read_int(entry, "cap_cents", required=True, minimum=0)
        if code in seen:
            bad("duplicate add-on code '%s'" % code)
        seen.add(code)
        add_ons.append({"code": code, "rate_pct": rate, "cap_cents": cap})
    return add_ons


def read_new_line_items(body, key="new_line_items", required=False):
    raw = read_list(body, key, required=required, default=None)
    if raw is None:
        return None
    if len(raw) < 1:
        bad("field '%s' must contain at least one entry" % key)
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            bad("each '%s' entry must be an object" % key)
        for field in entry.keys():
            if field not in ("sku", "item_description", "unit_of_measure",
                             "base_unit_price_cents", "price_floor_cents"):
                bad("unknown field '%s' in %s entry" % (field, key))
        items.append({
            "sku": read_str(entry, "sku", required=True, min_len=1, max_len=40),
            "item_description": read_str(entry, "item_description", required=True,
                                         min_len=1, max_len=500),
            "unit_of_measure": read_str(entry, "unit_of_measure", required=True,
                                        enum=UNITS_OF_MEASURE),
            "base_unit_price_cents": read_int(entry, "base_unit_price_cents",
                                              required=True, minimum=1),
            "price_floor_cents": read_int(entry, "price_floor_cents",
                                          required=True, minimum=0),
        })
    return items


def read_reciprocity_codes(body, key="reciprocity_state_codes", own_code=None):
    raw = read_list(body, key, required=False, default=None)
    if raw is None:
        return []
    codes = []
    for value in raw:
        if not isinstance(value, str):
            bad("each '%s' entry must be a string" % key)
        check_state_code(value, key)
        if own_code is not None and value == own_code:
            bad("'%s' must not contain the rule's own state_code" % key)
        codes.append(value)
    return codes


# --------------------------------------------------------------------------
# query string
# --------------------------------------------------------------------------

def query_args(allowed=()):
    allowed = set(allowed) | {"limit", "offset"}
    for key in request.args.keys():
        if key not in allowed:
            bad("unknown query parameter '%s'" % key)
    return request.args


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT
    if raw_limit is not None:
        limit = _as_int(raw_limit, "limit")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            bad("limit must be between %d and %d" % (PAGINATION_LIMIT_MIN,
                                                     PAGINATION_LIMIT_MAX))
    if raw_offset is not None:
        offset = _as_int(raw_offset, "offset")
        if offset < 0:
            bad("offset must be >= 0")
    return limit, offset


def _as_int(raw, name):
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        bad("%s must be an integer" % name)
    value = int(text)
    return value


def query_enum(args, key, enum):
    value = args.get(key)
    if value is None:
        return None
    if value not in enum:
        bad("query parameter '%s' must be one of %s" % (key, ", ".join(enum)))
    return value


def query_int(args, key, minimum=None):
    value = args.get(key)
    if value is None:
        return None
    parsed = _as_int(value, key)
    if minimum is not None and parsed < minimum:
        bad("query parameter '%s' must be >= %s" % (key, minimum))
    return parsed
