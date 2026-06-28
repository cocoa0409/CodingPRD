"""Shared helpers: rounding, pagination, body validation, calculation constants."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err

# ---------------------------------------------------------------------------
# Calculation constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
# order_total
TIER1_THRESHOLD = 5000
TIER1_PCT = Decimal("0.05")
TIER2_THRESHOLD = 15000
TIER2_PCT = Decimal("0.10")
FREE_SHIP_THRESHOLD = 10000
FLAT_SHIP_CENTS = 599

# commission
COMM_TIER1_THRESHOLD = 50000
COMM_TIER1_PCT = Decimal("0.20")
COMM_TIER2_THRESHOLD = 150000
COMM_TIER2_PCT = Decimal("0.25")
COMM_BASE_PCT = Decimal("0.15")

# retouch_cost
BASE_RETOUCH_FEE = 1500
PER_ADJUSTMENT_FEE = 500
COMP_PCT = Decimal("0.5")

# match_confidence_score
W_NAME = Decimal("0.5")
W_GRADE = Decimal("0.2")
W_HOMEROOM = Decimal("0.3")
MATCH_AUTO_THRESHOLD = 80

# scheduling
PHOTOGRAPHER_BUFFER_MIN = 10


def round_half_up(value):
    """Round a Decimal/number half-up to an integer (cents)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def commission_rate(gross):
    """Tiered commission rate by gross merchandise cents (SCAFFOLD §1.3)."""
    if gross >= COMM_TIER2_THRESHOLD:
        return COMM_TIER2_PCT
    if gross >= COMM_TIER1_THRESHOLD:
        return COMM_TIER1_PCT
    return COMM_BASE_PCT


# ---------------------------------------------------------------------------
# Body / pagination helpers
# ---------------------------------------------------------------------------
def get_body():
    """Parse the JSON body; tolerate empty body for action endpoints.
    A non-JSON / malformed body where one is required surfaces as a 422 later."""
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            data = request.get_json(silent=True)
        except Exception:
            data = None
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return data
    return {}


def parse_pagination():
    """Read limit/offset query params per PRD §2.3.
    limit default 10, min 1, max 100; offset default 0, min 0.
    Out-of-range / non-integer values -> ERR_INVALID_REQUEST (422)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(rows, limit, offset):
    """rows is an already-sorted list. Returns (page, total_count)."""
    total = len(rows)
    return rows[offset:offset + limit], total


def sort_by_creation(rows):
    """Sort by creation order ascending (PRD §2.3 default sort)."""
    return sorted(rows, key=lambda r: r["_seq"])


# ---------------------------------------------------------------------------
# Field validation primitives (all -> ERR_INVALID_REQUEST 422)
# ---------------------------------------------------------------------------
def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return val


def require_int(body, field):
    val = body.get(field)
    # bool is a subclass of int; reject it explicitly
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def require_enum(body, field, allowed):
    val = body.get(field)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val
