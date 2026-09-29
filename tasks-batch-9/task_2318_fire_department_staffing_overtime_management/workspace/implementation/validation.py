"""Request-shape validation (PRD 2.6 step 3 -> ERR_INVALID_REQUEST)."""

import json
import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

CERTIFICATIONS = ("PARAMEDIC", "HAZMAT_TECH", "TECHNICAL_RESCUE")
SEAT_CERTIFICATIONS = ("NONE",) + CERTIFICATIONS
APPARATUS_TYPES = ("ENGINE", "LADDER", "RESCUE", "MEDIC", "HAZMAT")
RANKS = ("FIREFIGHTER", "ENGINEER", "LIEUTENANT", "CAPTAIN")
PLATOONS = ("A", "B", "C", "D")
EMPLOYMENT_STATUSES = ("ACTIVE", "INJURY_LEAVE", "SEPARATED")
ROSTER_STANDINGS = ("AVAILABLE", "PASSED", "UNAVAILABLE")
ROSTER_TYPES = ("VOLUNTARY_OT", "MANDATORY_HOLDOVER", "CALLBACK")
APPARATUS_STATUSES = ("IN_SERVICE", "OUT_OF_SERVICE")
ASSIGNMENT_TYPES = ("REGULAR", "KELLY_RELIEF", "OVERTIME", "HOLDOVER", "CALLBACK", "TRADE")
LEAVE_TYPES = ("INJURY", "SICK", "KELLY_DAY", "BEREAVEMENT", "VACATION")
HIRING_MODES = ("VOLUNTARY", "MANDATORY_HOLDOVER", "CALLBACK")
OFFER_RESPONSES = ("ACCEPT", "DECLINE")
TRADE_DECISIONS = ("APPROVE", "REJECT", "RETURN_FOR_REVISION")
ADJUSTMENT_BASES = ("SCHEDULED", "WORKED")
FORECAST_METHODS = ("VACANCY_DRIVEN", "RUN_RATE")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?(?:[Zz]|[+-]\d{2}:?\d{2})$"
)


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_datetime(value):
    if not isinstance(value, str) or not _DATETIME_RE.match(value):
        return None
    text = value.strip()
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def spec(name, kind, required=True, **opts):
    entry = {"name": name, "kind": kind, "required": required}
    entry.update(opts)
    return entry


def parse_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw) == 0:
        return {}
    try:
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        _bad("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        _bad("Request body must be a JSON object.")
    return body


def _coerce(entry, value):
    name = entry["name"]
    kind = entry["kind"]
    if kind == "string":
        if not isinstance(value, str):
            _bad("Field '%s' must be a string." % name)
        if entry.get("nonempty", True) and not value.strip():
            _bad("Field '%s' must not be empty." % name)
        return value
    if kind == "integer":
        if not is_int(value):
            _bad("Field '%s' must be an integer." % name)
        if "minimum" in entry and value < entry["minimum"]:
            _bad("Field '%s' must be >= %s." % (name, entry["minimum"]))
        if "maximum" in entry and value > entry["maximum"]:
            _bad("Field '%s' must be <= %s." % (name, entry["maximum"]))
        return value
    if kind == "number":
        if not is_num(value):
            _bad("Field '%s' must be a number." % name)
        if "exclusive_minimum" in entry and not value > entry["exclusive_minimum"]:
            _bad("Field '%s' must be > %s." % (name, entry["exclusive_minimum"]))
        if "minimum" in entry and value < entry["minimum"]:
            _bad("Field '%s' must be >= %s." % (name, entry["minimum"]))
        if "maximum" in entry and value > entry["maximum"]:
            _bad("Field '%s' must be <= %s." % (name, entry["maximum"]))
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad("Field '%s' must be a boolean." % name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in entry["values"]:
            _bad("Field '%s' must be one of %s." % (name, ", ".join(entry["values"])))
        return value
    if kind == "date":
        parsed = parse_date(value)
        if parsed is None:
            _bad("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % name)
        return value
    if kind == "datetime":
        parsed = parse_datetime(value)
        if parsed is None:
            _bad("Field '%s' must be an ISO 8601 UTC datetime." % name)
        return parsed
    if kind == "array_enum":
        if not isinstance(value, list):
            _bad("Field '%s' must be an array." % name)
        for element in value:
            if not isinstance(element, str) or element not in entry["values"]:
                _bad(
                    "Every element of '%s' must be one of %s."
                    % (name, ", ".join(entry["values"]))
                )
        return list(value)
    if kind == "id":
        if not isinstance(value, str) or not value.strip():
            _bad("Field '%s' must be a non-empty string identifier." % name)
        return value
    _bad("Unsupported field '%s'." % name)


def validate(body, specs):
    out = {}
    for entry in specs:
        name = entry["name"]
        if name not in body or body[name] is None:
            if entry["required"]:
                _bad("Field '%s' is required and must be non-null." % name)
            out[name] = entry.get("default")
            continue
        out[name] = _coerce(entry, body[name])
    return out
