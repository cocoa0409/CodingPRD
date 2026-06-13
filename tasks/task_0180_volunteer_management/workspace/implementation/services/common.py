"""Shared entity helpers: common fields, system timestamps, version bumps,
lookups, pagination, body validation (PRD §2.3, §2.4, §2.7).
"""
from flask import request

from db import store
from errors import ApiError
from timeutil import now_iso, parse_dt

# Fields included in each entity's serialized output, in declared order. The
# common system fields (id/created_at/updated_at/version) are appended by
# serialize() except for the three append-only records that carry only
# id/created_at.
APPEND_ONLY = {"volunteer_skills", "waiver_acceptances", "training_completions"}


# ---- creation / mutation --------------------------------------------------
def base_record(collection):
    """Create a record carrying common system fields. created_at/updated_at use
    the simulated clock; version starts at 1. Append-only collections get only
    id + created_at."""
    now = store.now()
    rec = {
        "id": store.new_id(),
        "created_at": now_iso(now),
        "_seq": store.next_seq(),
    }
    if collection not in APPEND_ONLY:
        rec["updated_at"] = now_iso(now)
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version (a mutation). No-op fields for
    append-only records are never present, so this is only called on mutables."""
    rec["updated_at"] = now_iso(store.now())
    rec["version"] = rec.get("version", 1) + 1


# ---- lookups --------------------------------------------------------------
_NOT_FOUND = {
    "organizations": "ERR_ORGANIZATION_NOT_FOUND",
    "volunteers": "ERR_VOLUNTEER_NOT_FOUND",
    "background_checks": "ERR_BG_CHECK_NOT_FOUND",
    "skills": "ERR_SKILL_NOT_FOUND",
    "waiver_templates": "ERR_WAIVER_TEMPLATE_NOT_FOUND",
    "training_modules": "ERR_TRAINING_MODULE_NOT_FOUND",
    "opportunities": "ERR_OPPORTUNITY_NOT_FOUND",
    "shifts": "ERR_SHIFT_NOT_FOUND",
    "signups": "ERR_SIGNUP_NOT_FOUND",
    "corporate_groups": "ERR_GROUP_NOT_FOUND",
}


def get_or_404(collection, rec_id):
    coll = getattr(store, collection)
    rec = coll.get(rec_id)
    if rec is None:
        raise ApiError(_NOT_FOUND[collection], "%s not found" % collection)
    return rec


def find_fk_or_404(collection, rec_id):
    """Resolve a body foreign key; same resource-specific 404 as path lookups."""
    return get_or_404(collection, rec_id)


def require_org_active(org):
    """PRD §2.7 step 5: a child create is blocked while the governing
    organization is ARCHIVED."""
    if org["status"] == "ARCHIVED":
        raise ApiError("ERR_ORGANIZATION_ARCHIVED", "Organization is archived")


# ---- body parsing ---------------------------------------------------------
def get_json():
    """Return the request JSON body as a dict, or {} if absent. A non-object
    body (e.g. a JSON array or scalar) is an invalid request."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_field(body, field, expected_types=None):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    value = body[field]
    if expected_types is not None and not isinstance(value, expected_types):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s has wrong type" % field)
    # bool is a subclass of int — reject when an int is expected but a bool given
    if expected_types in (int, (int,)) and isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s has wrong type" % field)
    return value


def optional_field(body, field, default, expected_types=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if expected_types is not None and not isinstance(value, expected_types):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s has wrong type" % field)
    if expected_types in (int, (int,)) and isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s has wrong type" % field)
    return value


def require_int(body, field):
    value = require_field(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return value


def require_number(body, field):
    value = require_field(body, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return value


# ---- pagination -----------------------------------------------------------
def paginate_params():
    """Read limit/offset query params with PRD §2.3 defaults and bounds.
    limit default 10, min 1, max 100; offset default 0, min 0. Out-of-range or
    non-integer values are rejected as ERR_INVALID_REQUEST."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit out of range")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset out of range")
    return limit, offset


def list_collection(collection, predicate=None):
    """Return (page_items_serialized, limit, offset, total_count) for a
    collection, sorted by created_at ASC (tie-broken by creation sequence)."""
    limit, offset = paginate_params()
    coll = getattr(store, collection)
    items = list(coll.values())
    if predicate is not None:
        items = [r for r in items if predicate(r)]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return page, limit, offset, total
