"""Request-shape validation (ladder priority 6), pagination, and lookups."""

import re

from flask import request

from db import db
from errors import fail
from util import parse_instant


# --------------------------------------------------------------------------
# field specs
# --------------------------------------------------------------------------

def f(name, kind, required=False, enum=None, lo=None, hi=None, regex=None,
      subset=None, nullable=False, nonempty=True):
    return {
        "name": name,
        "kind": kind,
        "required": required,
        "enum": enum,
        "lo": lo,
        "hi": hi,
        "regex": regex,
        "subset": subset,
        "nullable": nullable,
        "nonempty": nonempty,
    }


def raw_body():
    body = request.get_json(silent=True, force=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_VALIDATION", "request body must be a JSON object")
    return body


def _coerce(spec, value):
    name = spec["name"]
    kind = spec["kind"]
    if kind == "string":
        if not isinstance(value, str):
            fail("ERR_VALIDATION", "%s must be a string" % name)
        if spec["nonempty"] and not value.strip():
            fail("ERR_VALIDATION", "%s must not be empty" % name)
        if spec["regex"] and not re.match(spec["regex"], value):
            fail("ERR_VALIDATION", "%s does not match the required format" % name)
        return value
    if kind == "enum":
        if not isinstance(value, str):
            fail("ERR_VALIDATION", "%s must be a string" % name)
        if value not in spec["enum"]:
            fail("ERR_VALIDATION", "%s must be one of %s" % (name, ", ".join(spec["enum"])))
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            fail("ERR_VALIDATION", "%s must be an integer" % name)
        if spec["lo"] is not None and value < spec["lo"]:
            fail("ERR_VALIDATION", "%s must be at least %s" % (name, spec["lo"]))
        if spec["hi"] is not None and value > spec["hi"]:
            fail("ERR_VALIDATION", "%s must be at most %s" % (name, spec["hi"]))
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            fail("ERR_VALIDATION", "%s must be a boolean" % name)
        return value
    if kind == "instant":
        parsed = parse_instant(value)
        if parsed is None:
            fail("ERR_VALIDATION", "%s must be an ISO 8601 instant" % name)
        return parsed
    if kind == "array":
        if not isinstance(value, list):
            fail("ERR_VALIDATION", "%s must be an array" % name)
        for item in value:
            if not isinstance(item, str):
                fail("ERR_VALIDATION", "%s must be an array of strings" % name)
            if spec["subset"] is not None and item not in spec["subset"]:
                fail("ERR_VALIDATION", "%s contains an unsupported value" % name)
        if spec["nonempty"] and len(value) == 0:
            fail("ERR_VALIDATION", "%s must not be empty" % name)
        return list(value)
    raise AssertionError("unknown kind %s" % kind)


def validate_body(specs, body=None):
    """Return {field: parsed} for every supplied field, enforcing priority 6."""
    if body is None:
        body = raw_body()
    out = {}
    for spec in specs:
        name = spec["name"]
        present = name in body
        value = body.get(name)
        if present and value is None:
            if spec["nullable"]:
                out[name] = None
                continue
            present = False
        if not present:
            if spec["required"]:
                fail("ERR_VALIDATION", "%s is required" % name)
            continue
        out[name] = _coerce(spec, value)
    return out


# --------------------------------------------------------------------------
# pagination and query filters
# --------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        text = args.get("limit")
        if not re.match(r"^-?\d+$", (text or "").strip()):
            fail("ERR_VALIDATION", "limit must be an integer")
        limit = int(text.strip())
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100")
    if "offset" in args:
        text = args.get("offset")
        if not re.match(r"^-?\d+$", (text or "").strip()):
            fail("ERR_VALIDATION", "offset must be an integer")
        offset = int(text.strip())
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be at least 0")
    return limit, offset


def query_values(specs):
    """Validate declared query filters; returns {name: raw string} for supplied ones."""
    out = {}
    for spec in specs:
        name = spec["name"]
        if name not in request.args:
            continue
        value = request.args.get(name)
        if value is None or value == "":
            continue
        if spec["kind"] == "enum" and value not in spec["enum"]:
            fail("ERR_VALIDATION", "%s must be one of %s" % (name, ", ".join(spec["enum"])))
        if spec["kind"] == "bool":
            if value.lower() not in ("true", "false"):
                fail("ERR_VALIDATION", "%s must be a boolean" % name)
            out[name] = value.lower() == "true"
            continue
        out[name] = value
    return out


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# --------------------------------------------------------------------------
# existence
# --------------------------------------------------------------------------

def lookup(collection, row_id, error_id):
    if not isinstance(row_id, str):
        fail(error_id)
    row = getattr(db, collection).get(row_id)
    if row is None:
        fail(error_id)
    return row


def port_or_404(pid):
    return lookup("ports", pid, "ERR_PORT_NOT_FOUND")


def meeting_point_or_404(pid):
    return lookup("meeting_points", pid, "ERR_MEETING_POINT_NOT_FOUND")


def port_call_or_404(pid):
    return lookup("port_calls", pid, "ERR_PORT_CALL_NOT_FOUND")


def tender_wave_or_404(pid):
    return lookup("tender_waves", pid, "ERR_TENDER_WAVE_NOT_FOUND")


def operator_or_404(pid):
    return lookup("operators", pid, "ERR_OPERATOR_NOT_FOUND")


def audit_or_404(pid):
    return lookup("audits", pid, "ERR_AUDIT_NOT_FOUND")


def excursion_or_404(pid):
    return lookup("excursions", pid, "ERR_EXCURSION_NOT_FOUND")


def departure_or_404(pid):
    return lookup("departures", pid, "ERR_DEPARTURE_NOT_FOUND")


def guest_or_404(pid):
    return lookup("guests", pid, "ERR_GUEST_NOT_FOUND")


def booking_or_404(pid):
    return lookup("bookings", pid, "ERR_BOOKING_NOT_FOUND")


def ledger_or_404(pid):
    return lookup("ledger", pid, "ERR_LEDGER_ENTRY_NOT_FOUND")


def incident_or_404(pid):
    return lookup("incidents", pid, "ERR_INCIDENT_NOT_FOUND")


def claim_or_404(pid):
    return lookup("claims", pid, "ERR_CLAIM_NOT_FOUND")


def statement_or_404(pid):
    return lookup("statements", pid, "ERR_STATEMENT_NOT_FOUND")
