"""Input well-formedness (ERR_INVALID_REQUEST, 400) vs semantic bounds (ERR_VALIDATION, 422).

PRD §2.4: missing required field / wrong type / out-of-set enum -> ERR_INVALID_REQUEST.
Well-typed but out-of-bounds (negative counts, base_risk not in 0..40,
required_inspection_count not in 0..5, bad risk_tier, bad term_months) -> ERR_VALIDATION.
"""
from flask import request

import errors

RISK_TIERS = {"LOW", "MEDIUM", "HIGH"}
TERM_MONTHS = {12, 24, 36}
ENDORSEMENT_KINDS = {"LATE_HOURS", "OUTDOOR_SEATING", "HAZMAT_HANDLING", "SIDEWALK_USE"}
INSPECTION_RESULTS = {"PASSED", "FAILED"}


def body():
    """Return the JSON body as a dict, or {} when absent. Malformed JSON -> 400."""
    if request.data:
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise errors.invalid_request("Malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Request body must be a JSON object")
        return data
    return {}


def require(data, field):
    if field not in data or data[field] is None:
        raise errors.invalid_request("Missing required field: {}".format(field))
    return data[field]


def require_str(data, field):
    val = require(data, field)
    if not isinstance(val, str):
        raise errors.invalid_request("Field {} must be a string".format(field))
    return val


def require_bool(data, field):
    val = require(data, field)
    if not isinstance(val, bool):
        raise errors.invalid_request("Field {} must be a boolean".format(field))
    return val


def require_int(data, field):
    """Required integer with a bare type check (bool is not an int here)."""
    val = require(data, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field {} must be an integer".format(field))
    return val


def optional_int(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("Field {} must be an integer".format(field))
    return val


def require_enum(data, field, allowed):
    val = require(data, field)
    if not isinstance(val, str) or val not in allowed:
        raise errors.invalid_request("Field {} must be one of {}".format(field, sorted(allowed)))
    return val


def require_array(data, field):
    val = require(data, field)
    if not isinstance(val, list):
        raise errors.invalid_request("Field {} must be an array".format(field))
    return val
