"""Common record helpers: field stamping, body parsing, pagination, lookup.

Common fields (PRD §2.4): id, created_at, updated_at, version. Append-only audit
facts (privacy-consents, trip events, risk snapshots, discount grants) carry only
id + created_at.
"""
from flask import request

import clock
import db
from errors import ApiError


# ---------------------------------------------------------------------------
# Record construction / mutation
# ---------------------------------------------------------------------------
def new_record(fields, common=True):
    """Create a base record. `common=True` -> id/created_at/updated_at/version;
    `common=False` (append-only fact) -> id/created_at only."""
    rec = {"id": db.new_id()}
    now = clock.iso_now()
    rec["created_at"] = now
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    rec.update(fields)
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation (PRD §2.4, §2.10).

    Only applies to records carrying the common fields.
    """
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = clock.iso_now()


def serialize(rec):
    """Strip internal-only fields (those prefixed with '_') for output."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_body():
    """Parse the JSON body; tolerate an empty body as {} for action endpoints."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise ApiError("ERR_VALIDATION")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION")
    return body


def require_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_VALIDATION", f"Field '{key}' is required and must be a string.")
    return v


def require_int(body, key):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' is required and must be an integer.")
    return v


def require_number(body, key):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' is required and must be a number.")
    return v


def optional_str(body, key, default=None):
    v = body.get(key, default)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", f"Field '{key}' must be a string.")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def pagination():
    """Parse limit/offset query params with PRD §2.3 defaults & bounds."""
    args = request.args
    limit = _parse_int_param(args.get("limit"), default=10)
    offset = _parse_int_param(args.get("offset"), default=0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_param(raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(records, limit, offset):
    """Sort by created_at ascending (tie-broken by insertion seq), then slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return [serialize(r) for r in page], total


# ---------------------------------------------------------------------------
# Lookup (PRD §2.5) — left-to-right path-id resolution -> ERR_NOT_FOUND
# ---------------------------------------------------------------------------
def find_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec
