"""Shared helpers: auth headers, body validation, pagination, mutation, serializers."""

import uuid

from flask import request

import calc
import clock
from db import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_PAGINATION_INVALID,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    raise_err,
)

ROLES = {"LRAdmin", "LRManager", "Negotiator", "ChiefNegotiator", "UnionRepresentative", "LegalCounsel"}
ALL_ROLES = ["LRAdmin", "LRManager", "Negotiator", "ChiefNegotiator", "UnionRepresentative", "LegalCounsel"]


# ---------------------------------------------------------------------------
# Auth (validation priorities 1-2)
# ---------------------------------------------------------------------------

def authenticate(allowed_roles):
    """Validate X-User-ID / X-User-Role and endpoint role permission.

    Returns (user_id, role). Priority 1 -> ERR_UNAUTHENTICATED, 2 -> ERR_UNAUTHORIZED_ROLE.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not user_id.strip() or not role.strip() or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "X-User-ID / X-User-Role headers missing, blank, or role not declared")
    if role not in allowed_roles:
        raise_err(ERR_UNAUTHORIZED_ROLE, "Role %s is not permitted for this endpoint" % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Body parsing and field validation (priority 4)
# ---------------------------------------------------------------------------

def get_body():
    if not request.is_json:
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def optional_body():
    """For endpoints whose body is optional (activate, archive, void)."""
    if not request.is_json:
        return {}
    try:
        body = request.get_json(silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def _bad(msg):
    raise_err(ERR_INVALID_REQUEST, msg)


def req_string(body, field):
    if field not in body or body[field] is None:
        _bad("Missing required field: %s" % field)
    if not isinstance(body[field], str) or not body[field].strip():
        _bad("Field %s must be a non-blank string" % field)
    return body[field]


def opt_string(body, field):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        _bad("Field %s must be a string" % field)
    return value


def req_int(body, field):
    if field not in body or body[field] is None:
        _bad("Missing required field: %s" % field)
    return _as_int(body[field], field)


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return _as_int(body[field], field)


def _as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field %s must be an integer" % field)
    return value


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    if not isinstance(body[field], bool):
        _bad("Field %s must be a boolean" % field)
    return body[field]


def opt_number(body, field):
    """Returns a float for the JSON number, or None."""
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field %s must be a number" % field)
    return value


def req_enum(body, field, members):
    if field not in body or body[field] is None:
        _bad("Missing required field: %s" % field)
    if body[field] not in members:
        _bad("Field %s must be one of %s" % (field, sorted(members)))
    return body[field]


def req_datetime(body, field):
    if field not in body or body[field] is None:
        _bad("Missing required field: %s" % field)
    parsed = clock.parse_dt(body[field])
    if parsed is None:
        _bad("Field %s must be an ISO 8601 datetime" % field)
    return parsed


def opt_datetime(body, field):
    if field not in body or body[field] is None:
        return None
    parsed = clock.parse_dt(body[field])
    if parsed is None:
        _bad("Field %s must be an ISO 8601 datetime" % field)
    return parsed


def req_id_list(body, field):
    if field not in body or body[field] is None:
        _bad("Missing required field: %s" % field)
    value = body[field]
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        _bad("Field %s must be an array of ids" % field)
    return list(value)


# ---------------------------------------------------------------------------
# Pagination (priority 4 variant: ERR_PAGINATION_INVALID)
# ---------------------------------------------------------------------------

def parse_pagination():
    args = request.args
    raw_limit = args.get("limit", "10")
    raw_offset = args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise_err(ERR_PAGINATION_INVALID, "limit must be an integer in [1, 100]")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise_err(ERR_PAGINATION_INVALID, "offset must be an integer >= 0")
    if limit < 1 or limit > 100:
        raise_err(ERR_PAGINATION_INVALID, "limit must be in [1, 100]")
    if offset < 0:
        raise_err(ERR_PAGINATION_INVALID, "offset must be >= 0")
    return limit, offset


def page(items, limit, offset):
    """items must already be sorted by (created_at, insertion seq)."""
    total = len(items)
    return items[offset:offset + limit], total


def sort_items(items):
    return sorted(items, key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_entity():
    now = clock.now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next(db.seq),
    }


def touch(entity):
    """Every mutation refreshes updated_at and increments version (cascades included)."""
    entity["updated_at"] = clock.now()
    entity["version"] += 1


def lookup(collection, entity_id, label):
    entity = collection.get(entity_id)
    if entity is None:
        raise_err(ERR_NOT_FOUND, "%s not found: %s" % (label, entity_id))
    return entity


def recompute_posture(agreement):
    agreement["posture"] = calc.compute_posture(agreement, clock.now())


def recompute_envelope(agreement):
    agreement["envelope_committed_cents"] = calc.envelope_committed(agreement["id"], db.proposals)


def recompute_open_request_count(union):
    count = 0
    for ir in db.requests.values():
        if ir["union_id"] == union["id"] and ir["status"] in ("RECEIVED", "ACKNOWLEDGED", "IN_PROGRESS", "OBJECTED"):
            count += 1
    union["open_information_request_count"] = count


# ---------------------------------------------------------------------------
# Serializers (copy public fields; datetimes -> ISO strings)
# ---------------------------------------------------------------------------

# Business datetimes serialize at whole-second precision (PRD §2.9); only
# created_at / updated_at carry three fractional digits (PRD §2.10).
_DT_SECOND_FIELDS = {
    "effective_date", "expiration_date", "start_at", "end_at", "ballot_close_at",
    "effective_start", "effective_end", "first_observed_date", "last_observed_date",
    "abandon_effective_date", "received_at", "due_at", "due_date",
}
_DT_MILLIS_FIELDS = {"created_at", "updated_at"}


def serialize(entity):
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        if key in _DT_SECOND_FIELDS:
            out[key] = clock.iso_seconds(value)
        elif key in _DT_MILLIS_FIELDS:
            out[key] = clock.iso(value)
        else:
            out[key] = value
    return out
