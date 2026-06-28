"""Shared helpers: common-field stamping, pagination, body parsing, validation."""
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import db, new_id, iso_now
from errors import err


def parse_iso8601(value, field):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Used for vessel_eta,
    entry_date, exam-slot windows, and the logical clock. A malformed value is
    a basic input-validation failure (ERR_VALIDATION).
    """
    if not isinstance(value, str) or value == "":
        raise err("ERR_VALIDATION", "Field %s must be an ISO 8601 datetime string." % field)
    raw = value
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err("ERR_VALIDATION", "Field %s is not a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Common system fields (PRD §2.4)
# ---------------------------------------------------------------------------
def stamp_create(record):
    """Set id, created_at, updated_at, version on a new record."""
    now_iso = iso_now(db.now())
    record["id"] = new_id()
    record["created_at"] = now_iso
    record["updated_at"] = now_iso
    record["version"] = 1
    return record


def bump_version(record):
    """Increment version by exactly 1 and refresh updated_at to the clock."""
    record["version"] = record["version"] + 1
    record["updated_at"] = iso_now(db.now())
    return record


# ---------------------------------------------------------------------------
# Body / query parsing
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def require_field(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", "Missing required field: %s" % field)
    return body[field]


def require_str(body, field, allow_empty=False):
    val = require_field(body, field)
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", "Field %s must be a string." % field)
    if not allow_empty and val == "":
        raise err("ERR_VALIDATION", "Field %s must be non-empty." % field)
    return val


def require_int(body, field):
    val = require_field(body, field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", "Field %s must be an integer." % field)
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", "Field %s must be an integer." % field)
    return val


def require_enum(body, field, choices):
    val = require_field(body, field)
    if val not in choices:
        raise err("ERR_VALIDATION", "Field %s must be one of %s." % (field, sorted(choices)))
    return val


def optional_enum(body, field, choices, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in choices:
        raise err("ERR_VALIDATION", "Field %s must be one of %s." % (field, sorted(choices)))
    return val


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3) — limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = _parse_pos("limit", args.get("limit"), default=10)
    offset = _parse_pos("offset", args.get("offset"), default=0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_pos(name, raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "Query param %s must be an integer." % name)


def paginate(items, limit, offset):
    """Sort by created_at ascending, then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def list_response(records, view, filters=None):
    """Apply optional equality filters, paginate, serialize, and respond.

    `filters` is a list of (query_param_name, record_field_name). When the
    query param is present, only records whose field equals it are kept.
    """
    from response import array_response  # local import to avoid cycle

    items = list(records)
    if filters:
        for param, field in filters:
            val = request.args.get(param)
            if val is not None and val != "":
                items = [r for r in items if r.get(field) == val]
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return array_response([view(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Format validators (ERR_INVALID_FORMAT)
# ---------------------------------------------------------------------------
_HTS_RE = re.compile(r"^\d{10}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def validate_hts(code):
    if not isinstance(code, str) or not _HTS_RE.match(code):
        raise err("ERR_INVALID_FORMAT", "hts_code must be exactly 10 digits.")


def validate_country(code):
    if not isinstance(code, str) or not _COUNTRY_RE.match(code):
        raise err("ERR_INVALID_FORMAT", "country_of_origin must be 2 uppercase letters.")


def validate_period_month(period):
    if not isinstance(period, str) or not _PERIOD_RE.match(period):
        raise err("ERR_INVALID_FORMAT", "period_month must match YYYY-MM.")


# ---------------------------------------------------------------------------
# Existence lookups (ERR_NOT_FOUND, 404)
# ---------------------------------------------------------------------------
def lookup(table, _id):
    rec = table.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Referenced resource does not exist.")
    return rec


def lookup_optional(table, _id):
    """For optional FKs: if id is provided it must exist; if None, returns None."""
    if _id is None:
        return None
    return lookup(table, _id)


# ---------------------------------------------------------------------------
# Rounding: round half up to integer cents.
# ---------------------------------------------------------------------------
def round_half_up_bps(value_cents, rate_bps):
    """round_half_up( value_cents * rate_bps / 10000 ) -> int cents."""
    result = (Decimal(value_cents) * Decimal(rate_bps) / Decimal(10000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(result)
