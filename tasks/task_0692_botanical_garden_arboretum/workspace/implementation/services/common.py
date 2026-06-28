"""Shared helpers: record lifecycle, body parsing, pagination, ownership.

Common fields (PRD §2.4): every persisted resource carries a server-minted `id`
(bare UUID), `created_at` / `updated_at` ISO8601-UTC-with-ms, and an integer
`version` that begins at 1 and increments by one on every mutation.
"""
from flask import request

import errors
from db import db, new_id, now


def new_record(fields):
    """Create a record dict with common fields populated (PRD §2.4)."""
    ts = now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    rec["_seq"] = db.next_seq()  # internal ordering key (not serialized)
    rec.update(fields)
    return rec


def touch(rec):
    """Mark a record mutated: refresh updated_at, increment version (PRD §2.5)."""
    rec["updated_at"] = now()
    rec["version"] = rec["version"] + 1


# --- Body parsing / validation (ERR_VALIDATION, PRD §2.7) -------------------
_MISSING = object()


def get_body():
    """Return the JSON body as a dict; reject non-object bodies."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.validation("Request body must be a JSON object")
    return data


def req_str(body, key):
    v = body.get(key, _MISSING)
    if v is _MISSING:
        raise errors.validation(f"Missing required field: {key}")
    if not isinstance(v, str):
        raise errors.validation(f"Field {key} must be a string")
    return v


def opt_str(body, key, default=""):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        raise errors.validation(f"Field {key} must be a string")
    return v


def req_int(body, key, min_value=None):
    v = body.get(key, _MISSING)
    if v is _MISSING:
        raise errors.validation(f"Missing required field: {key}")
    return _coerce_int(v, key, min_value)


def opt_int(body, key, default, min_value=None):
    if key not in body or body[key] is None:
        return default
    return _coerce_int(body[key], key, min_value)


def _coerce_int(v, key, min_value):
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"Field {key} must be an integer")
    if min_value is not None and v < min_value:
        raise errors.validation(f"Field {key} must be >= {min_value}")
    return v


def opt_number(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise errors.validation(f"Field {key} must be a number")
    return v


def opt_bool(body, key, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise errors.validation(f"Field {key} must be a boolean")
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        raise errors.validation(f"Field {key} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, key, allowed, default):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str) or v not in allowed:
        raise errors.validation(f"Field {key} must be one of {sorted(allowed)}")
    return v


def req_str_array(body, key, default=None):
    if key not in body or body[key] is None:
        if default is not None:
            return list(default)
        raise errors.validation(f"Missing required field: {key}")
    v = body[key]
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise errors.validation(f"Field {key} must be an array of strings")
    return list(v)


# --- Pagination (PRD §2.3) -------------------------------------------------
def get_pagination():
    """Parse limit/offset query params; defaults 10/0, limit in [1,100]."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.validation("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            raise errors.validation("offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created_at ascending (oldest first) then page (PRD §2.3)."""
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


# --- Existence / ownership -------------------------------------------------
def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise errors.not_found()
    return rec


def resolve_membership_for_ownership(membership_id):
    """Return the owning Membership record or None (empty id => no owner)."""
    if not membership_id:
        return None
    return db.memberships.get(membership_id)


def check_owner(role, user_id, owning_membership_id):
    """Ownership gate for entity-backed Visitor mutations (PRD §2.1, priority 3).

    Operator roles bypass the comparison (opaque identity). For a Visitor, the
    owning membership's id must equal X-User-ID.

    PRD §2.1: "Ownership checks on any resource that references a `Membership`
    compare the resource's `membership_id` to `X-User-ID`." A resource that
    references no membership (empty membership_id — a non-member reservation,
    registration, or rental) is not member-owned, so no ownership check applies.
    """
    if role != "Visitor":
        return
    if not owning_membership_id:
        return
    if owning_membership_id != user_id:
        raise errors.not_resource_owner()
