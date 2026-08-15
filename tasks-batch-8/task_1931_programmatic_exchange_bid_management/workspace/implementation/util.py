"""Request-body validation helpers implementing PRD §2.8 pipeline stages 3-4.

Stage 3 (ERR_INVALID_REQUEST, 400): required field present, JSON types match,
numeric amounts positive where required, enum members valid.
Stage 4 (ERR_VALIDATION, 422): field-domain formats — dates YYYY-MM-DD,
datetimes ISO-8601 UTC, category_tags a non-empty array of strings,
write_off_reason non-empty where required.
"""

import re
from datetime import date

from flask import request

from db import parse_iso
from errors import invalid_request, validation

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_body():
    """Return the JSON request body as a dict; an empty body parses as {}.

    Malformed JSON or a non-object JSON value is a stage-3 shape failure.
    """
    data = request.get_data()
    if not data or not data.strip():
        return {}
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# strings
# ---------------------------------------------------------------------------

def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise invalid_request(f"{field} is required and must be a string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request(f"{field} must be a string")
    return v


# ---------------------------------------------------------------------------
# integers (JSON booleans are not integers)
# ---------------------------------------------------------------------------

def req_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if not _is_int(v):
        raise invalid_request(f"{field} is required and must be an integer")
    if min_v is not None and v < min_v:
        raise invalid_request(f"{field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise invalid_request(f"{field} must be <= {max_v}")
    return v


def opt_int(body, field, min_v=None, max_v=None):
    """Optional integer; an explicit JSON null reads as absent."""
    v = body.get(field)
    if v is None:
        return None
    if not _is_int(v):
        raise invalid_request(f"{field} must be an integer")
    if min_v is not None and v < min_v:
        raise invalid_request(f"{field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise invalid_request(f"{field} must be <= {max_v}")
    return v


def has_field(body, field):
    """True when the key is present with a non-null JSON value."""
    return field in body and body[field] is not None


# ---------------------------------------------------------------------------
# enums
# ---------------------------------------------------------------------------

def req_enum(body, field, values):
    v = body.get(field)
    if not isinstance(v, str) or v not in values:
        raise invalid_request(f"{field} must be one of {', '.join(sorted(values))}")
    return v


def opt_enum(body, field, values):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v not in values:
        raise invalid_request(f"{field} must be one of {', '.join(sorted(values))}")
    return v


# ---------------------------------------------------------------------------
# dates and datetimes (stage 4 formats -> ERR_VALIDATION)
# ---------------------------------------------------------------------------

def parse_date_field(value, field):
    if not isinstance(value, str):
        raise invalid_request(f"{field} is required and must be a YYYY-MM-DD date string")
    if not _DATE_RE.match(value.strip()):
        raise validation(f"{field} must match YYYY-MM-DD")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise validation(f"{field} must be a valid calendar date in YYYY-MM-DD")


def req_date(body, field):
    if field not in body or body[field] is None:
        raise invalid_request(f"{field} is required and must be a YYYY-MM-DD date string")
    return parse_date_field(body[field], field)


def opt_date(body, field):
    if not has_field(body, field):
        return None
    return parse_date_field(body[field], field)


def req_datetime(body, field):
    if field not in body or body[field] is None:
        raise invalid_request(f"{field} is required and must be an ISO 8601 UTC datetime string")
    v = body[field]
    if not isinstance(v, str):
        raise invalid_request(f"{field} is required and must be an ISO 8601 UTC datetime string")
    try:
        return parse_iso(v)
    except (ValueError, OverflowError):
        raise validation(f"{field} must be a well-formed ISO 8601 UTC datetime")


def opt_datetime(body, field):
    if not has_field(body, field):
        return None
    v = body[field]
    if not isinstance(v, str):
        raise invalid_request(f"{field} must be an ISO 8601 UTC datetime string")
    try:
        return parse_iso(v)
    except (ValueError, OverflowError):
        raise validation(f"{field} must be a well-formed ISO 8601 UTC datetime")


# ---------------------------------------------------------------------------
# category_tags: stage 4 pins "a non-empty array of strings"
# ---------------------------------------------------------------------------

def req_category_tags(body, field="category_tags"):
    v = body.get(field)
    if not isinstance(v, list):
        raise invalid_request(f"{field} is required and must be an array of strings")
    if len(v) == 0:
        raise validation(f"{field} must be a non-empty array of strings")
    for item in v:
        if not isinstance(item, str):
            raise validation(f"{field} entries must be strings")
    return list(v)


def opt_category_tags(body, field="category_tags"):
    if not has_field(body, field):
        return None
    return req_category_tags(body, field)
