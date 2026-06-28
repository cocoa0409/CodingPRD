"""Body field validators -> ERR_INVALID_REQUEST (priority 4).

Enum sets, numeric ranges, and required-field presence per the scaffold entity
constraints (§1.1) and PRD §3.
"""
from errors import err

EXAM_TYPES = {"SAT", "ACT", "MCAT", "LSAT"}
FORMATS = {"LIVE", "ONLINE", "SELF"}
ATTEMPT_TYPES = {"DIAGNOSTIC", "PRACTICE"}
RESOLUTIONS = {"REFUND", "RETAKE"}
NUM_INSTALLMENTS = {1, 2, 3, 4, 6, 12}
COUPONS = {"EARLYBIRD", "REFER50"}


def _bad(msg):
    raise err("ERR_INVALID_REQUEST", msg)


def require(body, field):
    if field not in body or body[field] is None:
        _bad(f"Missing required field: {field}")
    return body[field]


def is_int(value):
    # bool is a subclass of int; reject it as an integer field value.
    return isinstance(value, int) and not isinstance(value, bool)


def require_int(body, field, minimum=None, maximum=None):
    val = require(body, field)
    if not is_int(val):
        _bad(f"{field} must be an integer.")
    if minimum is not None and val < minimum:
        _bad(f"{field} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        _bad(f"{field} must be <= {maximum}.")
    return val


def require_number(body, field, minimum=None, maximum=None):
    val = require(body, field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _bad(f"{field} must be a number.")
    if minimum is not None and val < minimum:
        _bad(f"{field} must be >= {minimum}.")
    if maximum is not None and val > maximum:
        _bad(f"{field} must be <= {maximum}.")
    return val


def require_str(body, field):
    val = require(body, field)
    if not isinstance(val, str) or val == "":
        _bad(f"{field} must be a non-empty string.")
    return val


def require_enum(body, field, allowed):
    val = require(body, field)
    if val not in allowed:
        _bad(f"{field} must be one of {sorted(allowed)}.")
    return val
