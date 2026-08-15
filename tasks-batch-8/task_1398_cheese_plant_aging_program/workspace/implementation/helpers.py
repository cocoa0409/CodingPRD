"""Request parsing, auth, existence, filtering and pagination helpers.

Validation priority (PRD 2.9): auth (401) -> authorization (403) ->
well-formedness (400, at parse time, before business rules) -> existence
(404, left-to-right) -> OCC (412) -> state (409) -> business rungs 6-13.
"""

import json
from datetime import datetime, timezone

from flask import request

from db import STORES
from errors import ApiError, invalid_request, not_found, unauthenticated, unauthorized

ROLES = {
    "PlantAdmin",
    "MilkReceiver",
    "MakePlanner",
    "Cheesemaker",
    "QAGrader",
    "AgingRoomOperator",
    "SalesPlanner",
    "CutWrapOperator",
    "ComplianceOfficer",
}

ALL_ROLES = tuple(sorted(ROLES))


def auth(*allowed):
    """Priority 1 (authentication) then 2 (authorization). Returns (uid, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or role not in ROLES:
        unauthenticated()
    if allowed and role not in allowed:
        unauthorized()
    return uid, role


def body(required=True):
    """Parse the JSON request body; malformed JSON fails with 400."""
    raw = request.get_data()
    if raw is None or raw == b"":
        if required:
            invalid_request("Request body is required")
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        invalid_request("Request body is not valid JSON")
    if not isinstance(parsed, dict):
        invalid_request("Request body must be a JSON object")
    return parsed


# --- field validators ------------------------------------------------------

def _missing(b, name):
    return name not in b or b[name] is None


def f_str(b, name, required=True, default=None):
    if _missing(b, name):
        if required:
            invalid_request(f"Field '{name}' is required")
        return default
    v = b[name]
    if not isinstance(v, str):
        invalid_request(f"Field '{name}' must be a string")
    return v


def f_num(b, name, required=True, default=None, positive=False, non_negative=False):
    if _missing(b, name):
        if required:
            invalid_request(f"Field '{name}' is required")
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid_request(f"Field '{name}' must be a number")
    if positive and not v > 0:
        invalid_request(f"Field '{name}' must be positive")
    if non_negative and v < 0:
        invalid_request(f"Field '{name}' must be non-negative")
    return v


def f_int(b, name, required=True, default=None, positive=False, non_negative=False):
    if _missing(b, name):
        if required:
            invalid_request(f"Field '{name}' is required")
        return default
    v = b[name]
    if isinstance(v, bool) or not isinstance(v, int):
        invalid_request(f"Field '{name}' must be an integer")
    if positive and not v > 0:
        invalid_request(f"Field '{name}' must be positive")
    if non_negative and v < 0:
        invalid_request(f"Field '{name}' must be non-negative")
    return v


def f_bool(b, name, required=True, default=None):
    if _missing(b, name):
        if required:
            invalid_request(f"Field '{name}' is required")
        return default
    v = b[name]
    if not isinstance(v, bool):
        invalid_request(f"Field '{name}' must be a boolean")
    return v


def f_enum(b, name, values, required=True, default=None):
    if _missing(b, name):
        if required:
            invalid_request(f"Field '{name}' is required")
        return default
    v = b[name]
    if not isinstance(v, str) or v not in values:
        invalid_request(f"Field '{name}' must be one of {sorted(values)}")
    return v


def parse_dt(raw):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not isinstance(raw, str):
        invalid_request("Timestamp must be an ISO 8601 string")
    text = raw.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        invalid_request(f"Timestamp '{raw}' is not valid ISO 8601")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def f_dt(b, name, required=True):
    """Returns (raw_string, parsed_utc_datetime)."""
    if _missing(b, name):
        if required:
            invalid_request(f"Field '{name}' is required")
        return None, None
    raw = b[name]
    return raw, parse_dt(raw)


# --- existence / lookup ----------------------------------------------------

def get_or_404(store, rid, label=None):
    rec = STORES[store].get(rid) if isinstance(rid, str) else None
    if rec is None:
        not_found(f"{label or store} id '{rid}' does not exist")
    return rec


# --- list endpoints --------------------------------------------------------

def pagination_params():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            invalid_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            invalid_request("offset must be an integer")
        if offset < 0:
            invalid_request("offset must be non-negative")
    return limit, offset


def filter_and_page(store, filters, serializer):
    """filters: list of (field_name, raw_query_value); None values are skipped.
    Sorts by created_at ascending (creation order breaks ties)."""
    items = sorted(
        STORES[store].values(), key=lambda r: (r["created_at"], r["_seq"])
    )
    for field, raw in filters:
        if raw is None:
            continue
        items = [r for r in items if _matches(r, field, raw)]
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset : offset + limit]
    data = [serializer(r) for r in page]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return data, pagination


def _matches(rec, field, raw):
    v = rec.get(field)
    if isinstance(v, bool):
        return ("true" if v else "false") == raw
    if v is None:
        return False
    return str(v) == raw
