"""Shared helpers: ids, timestamps, common fields, body validation, dates,
pagination."""

import re
import uuid
from datetime import datetime, timezone, date

import db
from errors import err_invalid_request, err_not_found
from flask import request

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")

# Pagination defaults from SCAFFOLD §1.0 pagination_defaults
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.5)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def stamp_new(rec):
    ts = now_ts()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and bump version (PRD §2.5: every mutation)."""
    rec["updated_at"] = now_ts()
    rec["version"] += 1


def public(rec):
    """Strip internal bookkeeping keys before serialization."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_body():
    if not request.is_json:
        raise err_invalid_request("Request body must be JSON")
    try:
        body = request.get_json(silent=False)
    except Exception:
        raise err_invalid_request("Request body is not valid JSON")
    if body is None or not isinstance(body, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return body


def check_fields(body, required, optional=()):
    """Reject unknown keys first, then missing required keys (§2.11 malformed
    bodies are ERR_INVALID_REQUEST 400)."""
    allowed = set(required) | set(optional)
    for key in body:
        if key not in allowed:
            raise err_invalid_request("Unknown field: %s" % key)
    for key in required:
        if key not in body or body[key] is None:
            raise err_invalid_request("Missing required field: %s" % key)


def parse_date(value, field):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise err_invalid_request("%s must be an ISO date (YYYY-MM-DD)" % field)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise err_invalid_request("%s must be a valid calendar date" % field)


def valid_date_str(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def valid_period_str(value):
    if not isinstance(value, str) or not _PERIOD_RE.match(value):
        return False
    month = int(value[5:7])
    return 1 <= month <= 12


def parse_iso_instant(value):
    """Parse an ISO-8601 instant; accepts trailing Z. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err_invalid_request("%s must be a non-empty string" % field)
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request("%s must be an integer" % field)
    return v


def require_number(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request("%s must be a number" % field)
    return v


def require_enum(body, field, members):
    v = body.get(field)
    if v not in members:
        raise err_invalid_request("%s must be one of %s" % (field, ", ".join(sorted(members))))
    return v


def require_str_list(body, field, allowed=None):
    v = body.get(field)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise err_invalid_request("%s must be an array of strings" % field)
    if allowed is not None:
        for x in v:
            if x not in allowed:
                raise err_invalid_request("%s contains an invalid code: %s" % (field, x))
    return v


def resolve(table, entity_id):
    """Existence resolution (§2.11 tier 3)."""
    rec = table.get(entity_id)
    if rec is None:
        raise err_not_found()
    return rec


def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise err_invalid_request("limit must be between %d and %d" % (PAGE_MIN_LIMIT, PAGE_MAX_LIMIT))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def sort_chronological(records):
    """PRD §2.3: every list endpoint sorts by creation timestamp ascending."""
    return sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))


def apply_filters(records, filters):
    out = records
    for field, value in filters.items():
        if value is not None:
            out = [r for r in out if r.get(field) == value]
    return out
