"""Shared helpers: pagination, common-fields touch, OCC, serializers."""

from flask import g, request

from clock import now, to_iso
from db import DB, new_id
from errors import APIError, ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------

def stamp_create(obj: dict) -> dict:
    """Set id/created_at/updated_at/version on a fresh object."""
    obj.setdefault("id", new_id())
    n = to_iso(now())
    obj["created_at"] = n
    obj["updated_at"] = n
    obj["version"] = 1
    return obj


def stamp_create_minimal(obj: dict) -> dict:
    """For entities that only carry id and created_at (HsCode, TariffRule, ExchangeRate, DeclarationLine, InspectionAppointment, AuditEvent)."""
    obj.setdefault("id", new_id())
    obj["created_at"] = to_iso(now())
    return obj


def touch(obj: dict) -> dict:
    """Bump version + refresh updated_at on a mutated object that has both fields."""
    obj["version"] = int(obj.get("version", 1)) + 1
    obj["updated_at"] = to_iso(now())
    return obj


def check_occ(obj: dict, body: dict):
    """If body provided a `version` field, compare to current; mismatch -> 409."""
    if not isinstance(body, dict):
        return
    if "version" not in body:
        return
    submitted = body.get("version")
    if submitted is None:
        return
    try:
        submitted_int = int(submitted)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_STATE_TRANSITION, "Invalid version supplied", 409)
    if submitted_int != int(obj.get("version", 1)):
        raise APIError(ERR_INVALID_STATE_TRANSITION, "OCC version mismatch", 409)


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------

def get_body() -> dict:
    """Return JSON body as dict, or empty dict if absent."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return body


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def parse_pagination():
    """Read limit/offset from query string with PRD §2.3 defaults and bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None or str(raw_limit).strip() == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, "Invalid limit", 400)
    if raw_offset is None or str(raw_offset).strip() == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise APIError(ERR_INVALID_REQUEST, "Invalid offset", 400)
    if limit < 1:
        raise APIError(ERR_INVALID_REQUEST, "limit must be >= 1", 400)
    if limit > 100:
        raise APIError(ERR_INVALID_REQUEST, "limit must be <= 100", 400)
    if offset < 0:
        raise APIError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset


def paginate(items, limit: int, offset: int):
    total = len(items)
    sliced = items[offset:offset + limit]
    has_more = offset + limit < total
    return sliced, total, has_more


def sort_by_created_at(items):
    """Default sort: created_at ascending. created_at is an ISO 8601 UTC string."""
    return sorted(items, key=lambda x: x.get("created_at") or "")


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------

def emit_audit(subject_type: str, subject_id: str, event_type: str,
               before_value: dict = None, after_value: dict = None) -> dict:
    """Append an immutable AuditEvent row using the current request's actor."""
    actor_role = getattr(g, "role", None) or "system"
    actor_id = getattr(g, "user_id", None) or "system"
    ev = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "event_type": event_type,
        "before_value": before_value or {},
        "after_value": after_value or {},
    }
    stamp_create_minimal(ev)
    DB.audit_events.append(ev)
    return ev
