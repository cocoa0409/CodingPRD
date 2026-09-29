"""Request parsing plus ladder positions 4-16.

Positions 4-14  existence checks in the fixed entity order (event, claim,
                adjuster, housing block, deployment, inspection assignment,
                advance payment, vendor firm, vendor assignment, bulletin,
                file-transfer batch).  A path identifier of a type is always
                resolved before a body identifier of the same type.
Position 15     request-schema validation -> ERR_VALIDATION (422).
Position 16     interval well-formedness -> ERR_INVALID_WINDOW (422).
"""
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import fail
from store import dec, parse_dt

# --------------------------------------------------------------------------
# Body access
# --------------------------------------------------------------------------
_MISSING = object()


def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        payload = None
    if payload is None:
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return payload


def soft_body():
    """Parse the body without raising, so existence checks (4-14) can run first."""
    if not request.data:
        return {}
    payload = request.get_json(force=True, silent=True)
    return payload if isinstance(payload, dict) else {}


def raw_ref(payload, field):
    """Read a reference identifier for existence checking without typing it."""
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        return None
    return value


# --------------------------------------------------------------------------
# Existence resolution (positions 4-14)
# --------------------------------------------------------------------------
def _lookup(collection, value, error_id):
    if not isinstance(value, str):
        fail(error_id)
    rec = collection.get(value)
    if rec is None:
        fail(error_id)
    return rec


def event(value):
    return _lookup(store.events, value, "ERR_EVENT_NOT_FOUND")


def claim(value):
    return _lookup(store.claims, value, "ERR_CLAIM_NOT_FOUND")


def adjuster(value):
    return _lookup(store.adjusters, value, "ERR_ADJUSTER_NOT_FOUND")


def housing_block(value):
    return _lookup(store.housing_blocks, value, "ERR_HOUSING_BLOCK_NOT_FOUND")


def deployment(value):
    return _lookup(store.deployments, value, "ERR_DEPLOYMENT_NOT_FOUND")


def assignment(value):
    return _lookup(store.assignments, value, "ERR_ASSIGNMENT_NOT_FOUND")


def advance(value):
    return _lookup(store.advances, value, "ERR_ADVANCE_NOT_FOUND")


def vendor_firm(value):
    return _lookup(store.vendor_firms, value, "ERR_VENDOR_FIRM_NOT_FOUND")


def vendor_assignment(value):
    return _lookup(store.vendor_assignments, value, "ERR_VENDOR_ASSIGNMENT_NOT_FOUND")


def bulletin(value):
    return _lookup(store.bulletins, value, "ERR_BULLETIN_NOT_FOUND")


def batch(value):
    return _lookup(store.batches, value, "ERR_BATCH_NOT_FOUND")


def reserve_entry(value):
    # The catalogue declares no dedicated ledger-row 404, so the parent claim's
    # not-found identifier carries the 404 for an unknown ledger id.
    return _lookup(store.reserve_entries, value, "ERR_CLAIM_NOT_FOUND")


def loss_estimate(value):
    rec = store.loss_estimates.get(value) if isinstance(value, str) else None
    if rec is None:
        fail("ERR_EVENT_NOT_FOUND", "Loss estimate snapshot not found.")
    return rec


# --------------------------------------------------------------------------
# Schema validation (position 15)
# --------------------------------------------------------------------------
def _bad(field, why):
    fail("ERR_VALIDATION", "%s %s" % (field, why))


def present(payload, field):
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        _bad(field, "is required.")
    return value


def req_string(payload, field, min_len=1, max_len=None):
    value = present(payload, field)
    if not isinstance(value, str):
        _bad(field, "must be a string.")
    if len(value) < min_len:
        _bad(field, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters." % max_len)
    return value


def req_state(payload, field):
    value = req_string(payload, field)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        _bad(field, "must be a two-letter uppercase state code.")
    return value


def req_enum(payload, field, allowed):
    value = present(payload, field)
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s." % ", ".join(sorted(allowed)))
    return value


def opt_enum(payload, field, allowed, default=None):
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s." % ", ".join(sorted(allowed)))
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)


def req_int(payload, field, minimum=None, maximum=None):
    value = present(payload, field)
    if not _is_int(value):
        _bad(field, "must be an integer.")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %s." % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %s." % maximum)
    return value


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not _is_int(value):
        _bad(field, "must be an integer.")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %s." % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %s." % maximum)
    return value


def req_number(payload, field, minimum=None, maximum=None, exclusive_min=None):
    value = present(payload, field)
    if not _is_num(value):
        _bad(field, "must be a number.")
    try:
        value = dec(value)
    except (InvalidOperation, ValueError):
        _bad(field, "must be a number.")
    if minimum is not None and value < dec(minimum):
        _bad(field, "must be at least %s." % minimum)
    if exclusive_min is not None and value <= dec(exclusive_min):
        _bad(field, "must be greater than %s." % exclusive_min)
    if maximum is not None and value > dec(maximum):
        _bad(field, "must be at most %s." % maximum)
    return value


def opt_number(payload, field, minimum=None, maximum=None, default=None):
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not _is_num(value):
        _bad(field, "must be a number.")
    value = dec(value)
    if minimum is not None and value < dec(minimum):
        _bad(field, "must be at least %s." % minimum)
    if maximum is not None and value > dec(maximum):
        _bad(field, "must be at most %s." % maximum)
    return value


def req_bool(payload, field):
    value = present(payload, field)
    if not isinstance(value, bool):
        _bad(field, "must be a boolean.")
    return value


def opt_bool(payload, field, default=False):
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        _bad(field, "must be a boolean.")
    return value


def req_datetime(payload, field):
    value = present(payload, field)
    if not isinstance(value, str):
        _bad(field, "must be an ISO 8601 timestamp string.")
    parsed = parse_dt(value)
    if parsed is None:
        _bad(field, "must be an ISO 8601 timestamp string.")
    return parsed


def req_state_array(payload, field):
    value = present(payload, field)
    if not isinstance(value, list) or not value:
        _bad(field, "must be a non-empty array of state codes.")
    out = []
    for item in value:
        if not isinstance(item, str) or len(item) != 2 or not item.isalpha() \
                or item != item.upper():
            _bad(field, "entries must be two-letter uppercase state codes.")
        out.append(item)
    return out


COVERAGE_CODES = ("DWELLING", "CONTENTS", "ALE", "OTHER_STRUCTURES")


def req_coverage_lines(payload, field="coverage_lines"):
    value = present(payload, field)
    if not isinstance(value, list):
        _bad(field, "must be an array of 1 through 6 coverage lines.")
    if len(value) < 1 or len(value) > 6:
        _bad(field, "must hold between 1 and 6 entries.")
    seen = set()
    lines = []
    for item in value:
        if not isinstance(item, dict):
            _bad(field, "entries must be objects.")
        code = item.get("coverage_code")
        if not isinstance(code, str) or code not in COVERAGE_CODES:
            _bad(field, "coverage_code must be one of %s." % ", ".join(COVERAGE_CODES))
        if code in seen:
            _bad(field, "must not repeat a coverage_code.")
        seen.add(code)
        line = {"coverage_code": code}
        for money_field in ("limit_amount", "deductible_amount",
                            "estimated_damage_amount"):
            raw = item.get(money_field)
            if raw is None or not _is_num(raw):
                _bad(field, "%s must be a number on every entry." % money_field)
            if dec(raw) < 0:
                _bad(field, "%s must not be negative." % money_field)
            line[money_field] = float(dec(raw))
        lines.append(line)
    return lines


# --------------------------------------------------------------------------
# Interval well-formedness (position 16)
# --------------------------------------------------------------------------
def interval(start, end, message="End instant must be strictly later than start."):
    if end <= start:
        fail("ERR_INVALID_WINDOW", message)


# --------------------------------------------------------------------------
# Query-parameter helpers for list endpoints
# --------------------------------------------------------------------------
def query(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    fail("ERR_VALIDATION", "%s must be true or false." % name)
