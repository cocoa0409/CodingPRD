"""Authentication, authorization, path resolution and the body-shape passes
that implement validation priorities 1-19 of PRD §2.7."""

import json
from decimal import Decimal

from flask import request

import config
import db
import util
from errors import fail

MISSING = object()


# ---------------------------------------------------------------------------
# priorities 1-4: authentication and authorization
# ---------------------------------------------------------------------------
def authenticate(allowed_roles, resolve_picker=False):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    if role not in config.ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not one of the declared roles.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE")
    if role == config.ROLE_PICKER and resolve_picker:
        if user_id not in db.pickers:
            fail(
                "ERR_FORBIDDEN_ROLE",
                "X-User-ID does not resolve to an existing Picker row.",
            )
    return user_id, role


# ---------------------------------------------------------------------------
# priorities 5-9 / 16-19: existence
# ---------------------------------------------------------------------------
def _resolve(table, key, error_id):
    if not isinstance(key, str):
        fail(error_id)
    record = table.get(key)
    if record is None:
        fail(error_id)
    return record


def get_block(key):
    return _resolve(db.blocks, key, "ERR_BLOCK_NOT_FOUND")


def get_crew(key):
    return _resolve(db.crews, key, "ERR_CREW_NOT_FOUND")


def get_picker(key):
    return _resolve(db.pickers, key, "ERR_PICKER_NOT_FOUND")


def get_window(key):
    return _resolve(db.harvest_windows, key, "ERR_WINDOW_NOT_FOUND")


def get_session(key):
    return _resolve(db.pick_sessions, key, "ERR_SESSION_NOT_FOUND")


def get_run(key):
    return _resolve(db.payroll_runs, key, "ERR_PAYROLL_RUN_NOT_FOUND")


def get_lot(key):
    return _resolve(db.fruit_lots, key, "ERR_LOT_NOT_FOUND")


def get_tunnel(key):
    return _resolve(db.cooling_tunnels, key, "ERR_TUNNEL_NOT_FOUND")


def get_commitment(key):
    return _resolve(db.buyer_commitments, key, "ERR_COMMITMENT_NOT_FOUND")


def get_allocation(key):
    return _resolve(db.lot_allocations, key, "ERR_ALLOCATION_NOT_FOUND")


def get_water_test(key):
    return _resolve(db.water_tests, key, "ERR_WATER_TEST_NOT_FOUND")


# ---------------------------------------------------------------------------
# body reading — JSON numbers become Decimal so money and pounds stay exact
# ---------------------------------------------------------------------------
def read_body(required=True):
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        if required:
            return {}
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except Exception:
        if required:
            fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
        return {}
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        if required:
            fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return {}
    return parsed


class Field(object):
    """One declared body field."""

    def __init__(
        self,
        name,
        kind,
        required=True,
        enum=None,
        minimum=None,
        maximum=None,
        exclusive_min=None,
        exclusive_max=None,
        minlen=1,
        maxlen=None,
        nullable=False,
        scale=None,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_min = exclusive_min
        self.exclusive_max = exclusive_max
        self.minlen = minlen
        self.maxlen = maxlen
        self.nullable = nullable
        self.scale = scale


def _type_ok(kind, value):
    if isinstance(value, bool):
        return False
    if kind == "string":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int)
    if kind == "number":
        return isinstance(value, (int, Decimal))
    if kind in ("date", "instant"):
        return isinstance(value, str)
    return False


def check_shape(fields, body):
    """Priority 10 (+ string lengths): presence and declared JSON type."""
    for spec in fields:
        value = body.get(spec.name, MISSING)
        if value is MISSING:
            if spec.required:
                fail(
                    "ERR_INVALID_REQUEST",
                    "Required field '%s' is missing." % spec.name,
                )
            continue
        if value is None:
            if spec.nullable or not spec.required:
                continue
            fail("ERR_INVALID_REQUEST", "Field '%s' may not be null." % spec.name)
        if not _type_ok(spec.kind, value):
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' is not of the declared type." % spec.name,
            )
        if spec.kind == "string":
            if spec.minlen is not None and len(value) < spec.minlen:
                fail(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' is shorter than the declared minimum." % spec.name,
                )
            if spec.maxlen is not None and len(value) > spec.maxlen:
                fail(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' is longer than the declared maximum." % spec.name,
                )


def check_enums(fields, body):
    """Priority 11: enum-typed fields carry a declared value."""
    for spec in fields:
        if spec.enum is None:
            continue
        value = body.get(spec.name, MISSING)
        if value is MISSING or value is None:
            continue
        if value not in spec.enum:
            fail(
                "ERR_INVALID_ENUM",
                "Field '%s' carries an undeclared enum value." % spec.name,
            )


def check_ranges(fields, body):
    """Priority 12: numeric fields respect their declared ranges."""
    for spec in fields:
        if spec.kind not in ("int", "number"):
            continue
        value = body.get(spec.name, MISSING)
        if value is MISSING or value is None:
            continue
        num = util.dec(value)
        if spec.exclusive_min is not None and num <= util.dec(spec.exclusive_min):
            fail(
                "ERR_VALUE_OUT_OF_RANGE",
                "Field '%s' must be greater than %s." % (spec.name, spec.exclusive_min),
            )
        if spec.minimum is not None and num < util.dec(spec.minimum):
            fail(
                "ERR_VALUE_OUT_OF_RANGE",
                "Field '%s' is below its declared minimum." % spec.name,
            )
        if spec.exclusive_max is not None and num >= util.dec(spec.exclusive_max):
            fail(
                "ERR_VALUE_OUT_OF_RANGE",
                "Field '%s' must be less than %s." % (spec.name, spec.exclusive_max),
            )
        if spec.maximum is not None and num > util.dec(spec.maximum):
            fail(
                "ERR_VALUE_OUT_OF_RANGE",
                "Field '%s' is above its declared maximum." % spec.name,
            )


def parse_temporal(fields, body):
    """Priority 15: instants parse as RFC 3339 Z, dates as YYYY-MM-DD."""
    parsed = {}
    for spec in fields:
        if spec.kind not in ("date", "instant"):
            continue
        value = body.get(spec.name, MISSING)
        if value is MISSING or value is None:
            continue
        if spec.kind == "date":
            got = util.parse_date(value)
        else:
            got = util.parse_instant(value)
        if got is None:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' is not a valid %s." % (spec.name, spec.kind),
            )
        parsed[spec.name] = got
    return parsed


def tolerant(kind, value):
    """Parse without raising — used by priority 14, which must not pre-empt 15."""
    if not isinstance(value, str):
        return None
    return util.parse_date(value) if kind == "date" else util.parse_instant(value)


def validate_body(fields, body):
    """Run priorities 10, 11 and 12 in order."""
    check_shape(fields, body)
    check_enums(fields, body)
    check_ranges(fields, body)


def scaled(body, name, places, default=None):
    """Fetch a numeric body field quantized to its declared presentation scale."""
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    return util.q(value, places)
