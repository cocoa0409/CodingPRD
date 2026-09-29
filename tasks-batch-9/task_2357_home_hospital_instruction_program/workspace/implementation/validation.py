"""Tier-3 payload-shape validation (PRD §2.6 tier 3).

Every required field present, no unknown field, every enum value a member of its
declared set, every integer inside its declared range, every date formatted
`YYYY-MM-DD`, every datetime a valid ISO 8601 UTC instant, `physician_npi`
exactly ten digits, `hazard_findings` free of duplicate members, `limit` inside
the inclusive range 1 to 100, and `offset` not negative.  Any violation is
`ERR_VALIDATION` (400).
"""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import ApiError

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NPI_RE = re.compile(r"^\d{10}$")

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def fail(message):
    raise ApiError("ERR_VALIDATION", message)


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value):
    """Parse an ISO 8601 instant, normalising to UTC.  None when unparseable."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# body
# --------------------------------------------------------------------------

def _raw_body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("Request body must be a JSON object.")
    return parsed


def _coerce(name, value, spec):
    kind = spec.get("type", "string")

    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            fail("Field '%s' must be an integer." % name)
        if "min" in spec and value < spec["min"]:
            fail("Field '%s' is below its permitted minimum." % name)
        if "max" in spec and value > spec["max"]:
            fail("Field '%s' is above its permitted maximum." % name)
        return value

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("Field '%s' must be a number." % name)
        return value

    if kind == "boolean":
        if not isinstance(value, bool):
            fail("Field '%s' must be a boolean." % name)
        return value

    if kind == "string":
        if not isinstance(value, str):
            fail("Field '%s' must be a string." % name)
        if spec.get("enum") is not None and value not in spec["enum"]:
            fail("Field '%s' is not a member of its declared set." % name)
        if "min_len" in spec and len(value) < spec["min_len"]:
            fail("Field '%s' is shorter than permitted." % name)
        if "max_len" in spec and len(value) > spec["max_len"]:
            fail("Field '%s' is longer than permitted." % name)
        if spec.get("npi") and not NPI_RE.match(value):
            fail("Field '%s' must be exactly ten digits." % name)
        return value

    if kind == "date":
        if parse_date(value) is None:
            fail("Field '%s' must be a date formatted YYYY-MM-DD." % name)
        return value

    if kind == "datetime":
        if parse_datetime(value) is None:
            fail("Field '%s' must be a valid ISO 8601 UTC instant." % name)
        return value

    if kind == "array":
        if not isinstance(value, list):
            fail("Field '%s' must be an array." % name)
        if spec.get("non_empty") and not value:
            fail("Field '%s' must be a non-empty array." % name)
        members = spec.get("items_enum")
        for item in value:
            if not isinstance(item, str):
                fail("Field '%s' must contain only strings." % name)
            if members is not None and item not in members:
                fail("Field '%s' contains a value outside its declared set." % name)
        if spec.get("distinct") and len(set(value)) != len(value):
            fail("Field '%s' must not contain duplicate members." % name)
        return list(value)

    fail("Field '%s' could not be validated." % name)


def validate_body(spec):
    raw = _raw_body()
    spec = spec or {}
    for key in raw:
        if key not in spec:
            fail("Unknown field '%s' in request body." % key)
    out = {}
    for name, field_spec in spec.items():
        if name not in raw or raw[name] is None:
            if field_spec.get("required"):
                fail("Missing required field '%s'." % name)
            continue
        out[name] = _coerce(name, raw[name], field_spec)
    return out


# --------------------------------------------------------------------------
# query
# --------------------------------------------------------------------------

def _coerce_query(name, value, spec):
    kind = spec.get("type", "string")

    if kind == "boolean":
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        fail("Query parameter '%s' must be true or false." % name)

    if kind == "integer":
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            fail("Query parameter '%s' must be an integer." % name)
        if "min" in spec and parsed < spec["min"]:
            fail("Query parameter '%s' is below its permitted minimum." % name)
        if "max" in spec and parsed > spec["max"]:
            fail("Query parameter '%s' is above its permitted maximum." % name)
        return parsed

    if kind == "date":
        if parse_date(value) is None:
            fail("Query parameter '%s' must be a date formatted YYYY-MM-DD." % name)
        return value

    if spec.get("enum") is not None and value not in spec["enum"]:
        fail("Query parameter '%s' is not a member of its declared set." % name)
    return value


def validate_query(spec):
    """`spec` None means the endpoint declares no query input; nothing is read."""
    if spec is None:
        return {}
    full = dict(spec)
    full["limit"] = {
        "type": "integer",
        "min": PAGINATION_MIN_LIMIT,
        "max": PAGINATION_MAX_LIMIT,
    }
    full["offset"] = {"type": "integer", "min": 0}
    for key in request.args:
        if key not in full:
            fail("Unknown query parameter '%s'." % key)
    out = {}
    for name, field_spec in full.items():
        if name not in request.args:
            continue
        out[name] = _coerce_query(name, request.args.get(name), field_spec)
    out.setdefault("limit", PAGINATION_DEFAULT_LIMIT)
    out.setdefault("offset", PAGINATION_DEFAULT_OFFSET)
    return out
