"""Rank 4 shape validation, rank 5 pagination, rank 6/7 existence, rank 10 OCC."""

import json
from datetime import date, datetime, timezone

from flask import request

from db import db
from errors import fail
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

MISSING = object()


# --------------------------------------------------------------------------- #
# body parsing
# --------------------------------------------------------------------------- #
def body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


# --------------------------------------------------------------------------- #
# scalar field validation
# --------------------------------------------------------------------------- #
def _present(payload, key):
    return key in payload and payload[key] is not None


def _bad(key, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (key, why))


def req_string(payload, key, min_len=1, max_len=None):
    if not _present(payload, key):
        _bad(key, "is required")
    value = payload[key]
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(key, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(key, "must be at most %d characters" % max_len)
    return value


def opt_string(payload, key, default=None, min_len=1, max_len=None):
    if not _present(payload, key):
        return default
    return req_string(payload, key, min_len, max_len)


def _check_int(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be <= %s" % maximum)
    return value


def req_int(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        _bad(key, "is required")
    return _check_int(key, payload[key], minimum, maximum)


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    if not _present(payload, key):
        return default
    return _check_int(key, payload[key], minimum, maximum)


def _check_number(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(key, "must be a number")
    if minimum is not None and value < minimum:
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be <= %s" % maximum)
    return value


def req_number(payload, key, minimum=None, maximum=None):
    if not _present(payload, key):
        _bad(key, "is required")
    return _check_number(key, payload[key], minimum, maximum)


def opt_number(payload, key, default=None, minimum=None, maximum=None):
    if not _present(payload, key):
        return default
    return _check_number(key, payload[key], minimum, maximum)


def req_bool(payload, key):
    if not _present(payload, key):
        _bad(key, "is required")
    value = payload[key]
    if not isinstance(value, bool):
        _bad(key, "must be a boolean")
    return value


def opt_bool(payload, key, default=None):
    if not _present(payload, key):
        return default
    return req_bool(payload, key)


def req_enum(payload, key, allowed):
    value = req_string(payload, key, min_len=0)
    if value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(payload, key, allowed, default=None):
    if not _present(payload, key):
        return default
    return req_enum(payload, key, allowed)


def req_id(payload, key):
    return req_string(payload, key, min_len=1, max_len=None)


def opt_id(payload, key, default=None):
    if not _present(payload, key):
        return default
    return req_string(payload, key, min_len=1)


# --------------------------------------------------------------------------- #
# temporal parsing
# --------------------------------------------------------------------------- #
def parse_date_string(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10])) if (
            text[4] == "-" and text[7] == "-"
        ) else None
    except Exception:
        return None


def parse_instant_string(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_date(payload, key):
    raw = req_string(payload, key, min_len=1)
    parsed = parse_date_string(raw)
    if parsed is None:
        _bad(key, "must be an ISO 8601 calendar date (YYYY-MM-DD)")
    return parsed


def opt_date(payload, key, default=None):
    if not _present(payload, key):
        return default
    return req_date(payload, key)


def req_instant(payload, key):
    raw = req_string(payload, key, min_len=1)
    parsed = parse_instant_string(raw)
    if parsed is None:
        _bad(key, "must be an ISO 8601 UTC instant")
    return parsed


def opt_instant(payload, key, default=None):
    if not _present(payload, key):
        return default
    return req_instant(payload, key)


def date_str(value):
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def stored_date(value):
    """Parse a date we wrote ourselves."""
    return parse_date_string(value)


def stored_instant(value):
    return parse_instant_string(value)


# --------------------------------------------------------------------------- #
# query parameters
# --------------------------------------------------------------------------- #
def query_enum(key, allowed):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (key, ", ".join(allowed)))
    return raw


def query_string(key):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return None
    return raw


def query_bool(key):
    raw = request.args.get(key)
    if raw is None or raw == "":
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean" % key)


def pagination():
    """Rank 5 - ERR_INVALID_PAGINATION (HTTP 400)."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET

    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(str(raw_limit).strip())
        except Exception:
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")

    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(str(raw_offset).strip())
        except Exception:
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be >= 0")

    return limit, offset


# --------------------------------------------------------------------------- #
# existence (ranks 6 and 7)
# --------------------------------------------------------------------------- #
_NOT_FOUND = {
    "festivals": "ERR_FESTIVAL_NOT_FOUND",
    "budget_tiers": "ERR_BUDGET_TIER_NOT_FOUND",
    "stages": "ERR_STAGE_NOT_FOUND",
    "artists": "ERR_ARTIST_NOT_FOUND",
    "offers": "ERR_OFFER_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "radius_clauses": "ERR_RADIUS_CLAUSE_NOT_FOUND",
    "competing_performances": "ERR_COMPETING_PERFORMANCE_NOT_FOUND",
    "rider_items": "ERR_RIDER_ITEM_NOT_FOUND",
    "advance_packets": "ERR_ADVANCE_PACKET_NOT_FOUND",
    "payment_installments": "ERR_PAYMENT_INSTALLMENT_NOT_FOUND",
    "announcement_waves": "ERR_ANNOUNCEMENT_WAVE_NOT_FOUND",
}


def load(collection, row_id):
    row = getattr(db, collection).get(row_id)
    if row is None:
        fail(_NOT_FOUND[collection], "%s does not resolve to a stored row" % row_id)
    return row


def body_fk(payload, key, collection, required=True):
    """Resolve an identifier-bearing body field (rank 7)."""
    if not _present(payload, key):
        if required:
            _bad(key, "is required")
        return None
    value = req_string(payload, key, min_len=1)
    return load(collection, value)


# --------------------------------------------------------------------------- #
# optimistic concurrency (rank 10)
# --------------------------------------------------------------------------- #
def check_version(payload, key, row, error_id):
    expected = req_int(payload, key)
    if expected != row.get("version"):
        fail(error_id, "%s does not match the stored version" % key)
