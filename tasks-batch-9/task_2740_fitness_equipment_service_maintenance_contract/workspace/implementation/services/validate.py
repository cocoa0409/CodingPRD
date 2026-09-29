"""Request-shape validation (ladder rung 18 -> ERR_INVALID_REQUEST 400)."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

import db
from errors import ApiError

REGION_RE = re.compile(r"^[A-Z]{2,4}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def present(body, name):
    return name in body and body[name] is not None


def req(body, name):
    if not present(body, name):
        bad("%s is required" % name)
    return body[name]


def string(body, name, min_len=1, max_len=None, required=True, default=None):
    if not present(body, name):
        if required:
            bad("%s is required" % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if len(value) < min_len:
        bad("%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (name, max_len))
    return value


def identifier(body, name, required=True):
    """A referenced entity id: must be a non-empty string when supplied."""
    if not present(body, name):
        if required:
            bad("%s is required" % name)
        return None
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        bad("%s must be a non-empty string" % name)
    return value


def integer(body, name, minimum=None, maximum=None, required=True, default=None):
    if not present(body, name):
        if required:
            bad("%s is required" % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %s" % (name, maximum))
    return value


def number(body, name, minimum=None, maximum=None, required=True, default=None):
    """A numeric field returned as a Decimal built from its literal text."""
    if not present(body, name):
        if required:
            bad("%s is required" % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number" % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("%s must be a number" % name)
    if not dec.is_finite():
        bad("%s must be a finite number" % name)
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("%s must be >= %s" % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("%s must be <= %s" % (name, maximum))
    return dec


def boolean(body, name, required=False, default=False):
    if not present(body, name):
        if required:
            bad("%s is required" % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def enum(body, name, values, required=True, default=None):
    if not present(body, name):
        if required:
            bad("%s is required" % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in values:
        bad("%s must be one of %s" % (name, ", ".join(values)))
    return value


def instant(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            bad("%s is required" % name)
        return default
    value = body[name]
    parsed = db.parse_iso(value)
    if parsed is None:
        bad("%s must be an ISO 8601 UTC timestamp" % name)
    return parsed


def day(body, name, required=True, default=None):
    if not present(body, name):
        if required:
            bad("%s is required" % name)
        return default
    value = body[name]
    if not isinstance(value, str) or not DATE_RE.match(value):
        bad("%s must be a YYYY-MM-DD date" % name)
    try:
        parts = [int(p) for p in value.split("-")]
        date(parts[0], parts[1], parts[2])
    except (ValueError, IndexError):
        bad("%s must be a valid calendar date" % name)
    return value


def region_code(body, name, required=True):
    value = string(body, name, min_len=2, max_len=4, required=required)
    if value is None:
        return None
    if not REGION_RE.match(value):
        bad("%s must be 2 to 4 uppercase letters" % name)
    return value


def period_key(body, name):
    value = string(body, name, min_len=7, max_len=7)
    if not PERIOD_RE.match(value):
        bad("%s must be a YYYY-MM period key" % name)
    return value


def string_list(body, name, values, min_items=1, max_items=None, required=True):
    if not present(body, name):
        if required:
            bad("%s is required" % name)
        return None
    value = body[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if len(value) < min_items:
        bad("%s must carry at least %d entries" % (name, min_items))
    if max_items is not None and len(value) > max_items:
        bad("%s must carry at most %d entries" % (name, max_items))
    seen = []
    for item in value:
        if not isinstance(item, str) or item not in values:
            bad("%s entries must be one of %s" % (name, ", ".join(values)))
        if item in seen:
            bad("%s entries must be distinct" % name)
        seen.append(item)
    return seen


def checklist_template(body, name):
    """Up to twenty elements, each {code, is_safety_critical, consumable}."""
    if not present(body, name):
        return []
    value = body[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if len(value) > 20:
        bad("%s must carry at most 20 elements" % name)
    template = []
    codes = set()
    for element in value:
        if not isinstance(element, dict):
            bad("%s elements must be objects" % name)
        code = element.get("code")
        if not isinstance(code, str) or not (1 <= len(code) <= 40):
            bad("%s element code must be 1 to 40 characters" % name)
        if code in codes:
            bad("%s element codes must be unique" % name)
        codes.add(code)
        critical = element.get("is_safety_critical", False)
        consumable = element.get("consumable", False)
        if not isinstance(critical, bool):
            bad("%s element is_safety_critical must be a boolean" % name)
        if not isinstance(consumable, bool):
            bad("%s element consumable must be a boolean" % name)
        template.append({
            "code": code,
            "is_safety_critical": critical,
            "consumable": consumable,
        })
    return template


def expected_version(body, name="expected_contract_version"):
    """The OCC token: required by every endpoint that declares it."""
    return integer(body, name, minimum=0)
