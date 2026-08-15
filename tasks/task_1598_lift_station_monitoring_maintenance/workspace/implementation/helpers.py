"""Request-body validation, datetime/decimal parsing, pagination helpers."""
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

_MISSING = object()

ROLES = (
    "UtilityAdmin",
    "OperationsSupervisor",
    "OnCallOperator",
    "Operator",
    "MaintenancePlanner",
    "ComplianceOfficer",
    "CapitalProgramManager",
    "ScadaWebhook",
    "RegulatorPortal",
)

PUMP_STATUSES = ("IN_SERVICE", "STANDBY", "OUT_OF_SERVICE", "REBUILD")
ALARM_CLASSES = ("CRITICAL", "MAJOR", "MINOR", "INFO")
READING_SOURCES = ("SCADA", "MANUAL", "BACKFILL")
CERTS = ("CSE_1", "CSE_2", "ELEC_1", "GEN_OP", "COLLECTIONS_2")
TEST_KINDS = ("NO_LOAD", "LOAD_BANK", "TRANSFER_SWITCH")
CAUSE_CODES = (
    "GREASE_BLOCKAGE", "DEBRIS", "POWER_FAILURE", "PUMP_FAILURE",
    "INFLOW_INFILTRATION", "VANDALISM", "UNKNOWN",
)

STATION_CODE_RE = re.compile(r"^LS-[0-9]{4}$")
EMPLOYEE_CODE_RE = re.compile(r"^OP-[0-9]{4}$")
ASSET_TAG_RE = re.compile(r"^SP-[0-9]{4}$")


def body():
    """Return the JSON request body as a dict; {} when absent."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(b, key):
    v = b.get(key, _MISSING)
    if v is _MISSING or not isinstance(v, str) or v == "":
        bad("%s is required and must be a non-empty string" % key)
    return v


def opt_str(b, key, default=None):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, str):
        bad("%s must be a string" % key)
    return v


def req_int(b, key):
    v = b.get(key, _MISSING)
    if v is _MISSING or not is_int(v):
        bad("%s is required and must be an integer" % key)
    return v


def req_bool(b, key):
    v = b.get(key, _MISSING)
    if v is _MISSING or not isinstance(v, bool):
        bad("%s is required and must be a boolean" % key)
    return v


def opt_bool(b, key, default=False):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, bool):
        bad("%s must be a boolean" % key)
    return v


def req_enum(b, key, allowed):
    v = b.get(key, _MISSING)
    if v is _MISSING or not isinstance(v, str) or v not in allowed:
        bad("%s must be one of %s" % (key, ", ".join(allowed)))
    return v


def opt_enum(b, key, allowed, default=None):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        bad("%s must be one of %s" % (key, ", ".join(allowed)))
    return v


def parse_instant(s, field="timestamp"):
    """Parse an ISO-8601 instant (Z or offset) into an aware UTC datetime."""
    if not isinstance(s, str) or not s.strip():
        bad("%s must be an ISO-8601 timestamp string" % field)
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        bad("%s is not a valid ISO-8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_instant(b, key):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        bad("%s is required" % key)
    return parse_instant(v, key)


def to_decimal(v, field, places):
    """Coerce a JSON number to a Decimal quantized at `places`, round-half-up."""
    if not is_num(v):
        bad("%s must be a number" % field)
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        bad("%s must be a number" % field)
    q = Decimal(1).scaleb(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def req_decimal(b, key, places=2):
    v = b.get(key, _MISSING)
    if v is _MISSING or v is None:
        bad("%s is required" % key)
    return to_decimal(v, key, places)


def pagination_params():
    """limit/offset per PRD 2.3: default 10/0, bounds [1,100] / [0,inf)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer")
        if limit < 1 or limit > 100:
            bad("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer")
        if offset < 0:
            bad("offset must be >= 0")
    return limit, offset


def sort_items(items):
    """created_at ASC; identical logical-clock timestamps broken by insertion order."""
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


def paginate(items):
    """Slice a pre-filtered item list; return (page, pagination-meta-dict)."""
    ordered = sort_items(items)
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def num(d):
    """Serialize a Decimal as a JSON number."""
    if d is None:
        return None
    return float(d)
