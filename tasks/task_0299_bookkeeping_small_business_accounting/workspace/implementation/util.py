"""Shared route helpers: body parsing, pagination, list sorting/filtering,
datetime parsing, period checks.
"""
from datetime import datetime

from flask import request

import db
import errors


def get_json_body():
    """Parse JSON body, tolerating an empty body (returns {})."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, names):
    for n in names:
        if body.get(n) is None:
            raise errors.invalid_request("Missing required field: %s" % n)


def require_int(body, name, required=True, default=None, min_value=None):
    val = body.get(name)
    if val is None:
        if required:
            raise errors.invalid_request("Missing required field: %s" % name)
        return default
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request("%s must be an integer" % name)
    if min_value is not None and val < min_value:
        raise errors.invalid_request("%s must be >= %s" % (name, min_value))
    return val


def parse_pagination():
    """Read limit/offset (PRD §2.3): limit default 10, min 1, max 100; offset
    default 0. Out-of-range values are clamped to the valid range."""
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be an integer")
    try:
        offset = int(offset) if offset is not None else 0
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def sorted_records(records):
    """Sort by created_at ascending; break ties by insertion sequence (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(records):
    """records: already-filtered list. Returns (page_items, limit, offset, total)."""
    limit, offset = parse_pagination()
    ordered = sorted_records(records)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


def parse_dt(value):
    """Parse an ISO 8601 datetime string into a comparable datetime. Tolerates a
    trailing 'Z'. Raises ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str):
        raise errors.invalid_request("Invalid datetime value")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        raise errors.invalid_request("Invalid datetime value: %s" % value)


def within_period(entity_date_str, period):
    """True if entity_date falls within [start_date, end_date) (PRD §2.9)."""
    d = parse_dt(entity_date_str)
    start = parse_dt(period["start_date"])
    end = parse_dt(period["end_date"])
    return start <= d < end


# --- Existence helpers (raise the scaffold's exact error_ids) ---

def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec


def get_company_or_404(rid):
    return get_or_404(db.companies, rid)


def get_account_or_404(rid):
    """account_id existence surfaces as ERR_ACCOUNT_NOT_FOUND (PRD §3.11)."""
    rec = db.accounts.get(rid)
    if rec is None:
        raise errors.account_not_found()
    return rec
