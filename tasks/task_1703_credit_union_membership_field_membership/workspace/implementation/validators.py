"""Request body parsing and syntactic field validation (tier 4)."""
import json
import re
from datetime import date

from flask import request

from errors import ApiError

DOC_CODES = {
    "GOVERNMENT_ID",
    "EMPLOYER_LETTER",
    "ADDRESS_PROOF",
    "ASSOCIATION_CARD",
    "RELATIONSHIP_PROOF",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _fail(msg):
    raise ApiError("ERR_VALIDATION_FAILED", msg)


def get_body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        _fail("request body is not valid JSON")
    if not isinstance(data, dict):
        _fail("request body must be a JSON object")
    return data


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        _fail(f"{name} is required and must be a non-empty string")
    return v


def opt_str_or_null(body, name):
    """Returns (present, value). Value must be a string or null."""
    if name not in body:
        return False, None
    v = body[name]
    if v is not None and not isinstance(v, str):
        _fail(f"{name} must be a string or null")
    return True, v


def req_int(body, name):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(f"{name} is required and must be an integer")
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        _fail(f"{name} must be one of {sorted(allowed)}")
    return v


def parse_date_str(v):
    """Returns a datetime.date for a valid YYYY-MM-DD string, else None."""
    if not isinstance(v, str) or not _DATE_RE.match(v):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def req_date(body, name):
    v = body.get(name)
    if parse_date_str(v) is None:
        _fail(f"{name} is required and must be a valid YYYY-MM-DD date")
    return v


def req_doc_codes(body, name):
    v = body.get(name)
    if not isinstance(v, list) or any(not isinstance(x, str) or x not in DOC_CODES for x in v):
        _fail(f"{name} must be an array of recognized document codes")
    return list(v)


def req_str_array(body, name):
    v = body.get(name)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _fail(f"{name} must be an array of strings")
    return list(v)


def parse_iso8601(v):
    """Parse an ISO 8601 datetime string into an aware datetime, else None."""
    if not isinstance(v, str) or not v:
        return None
    s = v.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt
