"""Shared helpers: common fields, request parsing, validation primitives,
deterministic-clock timestamp formatting, pagination."""
from datetime import datetime, timezone

from flask import request

from db import new_id
from errors import ERR_INVALID_REQUEST, raise_error

EPOCH_UTC = "1970-01-01T00:00:00.000Z"

VALID_ROLES = {"ProgramAdmin", "Clinician", "BillingAgent", "Coach", "Member"}


# --- wall-clock timestamp (created_at/updated_at use real time per PRD 2.4;
#     these are the resource lifecycle stamps, distinct from business-clock
#     fields like recorded_utc which read program.current_utc) ---
def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# monotonic creation counter so created_at ordering is stable even within the
# same millisecond (PRD 2.3 sort by creation timestamp ascending).
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def init_common(obj):
    """Attach id, created_at, updated_at, version (=1) to a full resource."""
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def init_event(obj):
    """Append-only event records carry only id + created_at (PRD 2.4)."""
    obj["id"] = new_id()
    obj["created_at"] = now_iso()
    obj["_seq"] = next_seq()
    return obj


def touch(obj):
    """Mutation bump: updated_at refreshed, version incremented (PRD 2.4)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1


def public(obj):
    """Strip private bookkeeping keys before serialising."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}


# --- request body parsing ---
def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        if request.content_length in (None, 0) and not request.data:
            return {}
        data = request.get_json(silent=True)
        if data is None:
            # No body / unparseable body -> treat as empty dict for endpoints
            # that take no input; mutating endpoints with required fields will
            # fail the required-field check below.
            if request.data:
                raise_error(ERR_INVALID_REQUEST, "Malformed JSON body")
            return {}
        if not isinstance(data, dict):
            raise_error(ERR_INVALID_REQUEST, "Body must be a JSON object")
        return data
    return {}


# --- field validators (all raise ERR_INVALID_REQUEST on failure) ---
def require(body, field):
    if field not in body or body[field] is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return body[field]


def as_str(value, field, allow_empty=False):
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a string")
    if not allow_empty and value.strip() == "":
        raise_error(ERR_INVALID_REQUEST, f"{field} must be non-empty")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be an integer")
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"{field} must be a number")
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return value


# --- pagination (PRD 2.3) ---
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error(ERR_INVALID_REQUEST, "limit out of range (1..100)")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_error(ERR_INVALID_REQUEST, "offset must be >= 0")

    return limit, offset


def sort_by_creation(items):
    return sorted(items, key=lambda o: o["_seq"])
