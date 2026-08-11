"""Request-shape validators (PRD §2.8.5) and state-gate helpers (§2.8.6)."""
import math

from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_ENUM,
    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL,
)

PRODUCT_FORMS = ("IN_SHELL", "KERNEL", "HULL", "SHELL")
SIZE_SPECS = ("SPEC_20_22", "SPEC_23_25", "SPEC_25_27", "UNSIZED")
TEST_TYPES = ("MOISTURE_KERNEL", "AFLATOXIN", "KERNEL_GRADE")
LOT_STATUSES = (
    "RECEIVED", "SAMPLED", "GRADED", "ROUTED_IN_SHELL", "ROUTED_KERNEL",
    "PROCESSING", "PROCESSED", "REJECTED", "DISPOSED", "SETTLED",
)
LOT_TERMINAL = ("DISPOSED", "SETTLED")
RUN_STATUSES = ("QUEUED", "RUNNING", "COMPLETED", "CANCELLED")
RUN_TERMINAL = ("COMPLETED", "CANCELLED")
BATCH_STATUSES = ("SCHEDULED", "DRYING", "COMPLETED", "CANCELLED")
BATCH_TERMINAL = ("COMPLETED", "CANCELLED")
BIN_STATUSES = ("AVAILABLE", "FUMIGATING", "AERATING")
PLACEMENT_STATUSES = ("STORED", "FUMIGATION_HOLD", "QUARANTINED", "WITHDRAWN", "DISPOSED")
PLACEMENT_TERMINAL = ("WITHDRAWN", "DISPOSED")
FUMIGATION_STATUSES = ("SCHEDULED", "ACTIVE", "AERATING", "CLEARED", "CANCELLED")
FUMIGATION_TERMINAL = ("CLEARED", "CANCELLED")
CONTRACT_STATUSES = ("OPEN", "SUSPENDED", "FULFILLED", "CLOSED")
CONTRACT_TERMINAL = ("FULFILLED", "CLOSED")
SHIPMENT_STATUSES = ("PLANNED", "BLOCKED", "DELIVERED", "CANCELLED")
SHIPMENT_TERMINAL = ("DELIVERED", "CANCELLED")
SETTLEMENT_STATUSES = ("DRAFT", "ISSUED", "PAID", "CANCELLED")
SETTLEMENT_TERMINAL = ("PAID", "CANCELLED")


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def need(body, field):
    """Required field presence (and non-null)."""
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % field)
    return body[field]


def req_string(body, field):
    v = need(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be a non-empty string" % field)
    return v


def req_number(body, field):
    v = need(body, field)
    if not is_num(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be a number" % field)
    return v


def req_int(body, field):
    v = need(body, field)
    if not is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be an integer" % field)
    return v


def req_enum(body, field, allowed):
    v = need(body, field)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be a string" % field)
    if v not in allowed:
        raise ApiError(ERR_INVALID_ENUM, 400, "Field %s must be one of %s" % (field, list(allowed)))
    return v


def opt_enum_filter(args, field, allowed):
    """Validate an optional query-string enum filter; None when absent."""
    v = args.get(field)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError(ERR_INVALID_ENUM, 400, "Filter %s must be one of %s" % (field, list(allowed)))
    return v


def check_range(value, field, gt=None, ge=None, lt=None, le=None):
    ok = True
    if gt is not None and not (value > gt):
        ok = False
    if ge is not None and not (value >= ge):
        ok = False
    if lt is not None and not (value < lt):
        ok = False
    if le is not None and not (value <= le):
        ok = False
    if not ok:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s is out of range" % field)
    return value


def check_state(rec, valid_from, terminal, label):
    """Priority 6: terminal states -> ERR_ALREADY_TERMINAL, else ERR_INVALID_STATE."""
    status = rec["status"]
    if status in valid_from:
        return
    if status in terminal:
        raise ApiError(ERR_ALREADY_TERMINAL, 409, "%s is already in terminal state %s" % (label, status))
    raise ApiError(ERR_INVALID_STATE, 409, "%s is in state %s, expected one of %s" % (label, status, list(valid_from)))
