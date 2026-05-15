"""Common helpers: timestamping, OCC, audit log writer, serialization."""

from __future__ import annotations

from copy import deepcopy
from flask import g

import db
import clock
from errors import AppError, ERR_VERSION_CONFLICT, ERR_NOT_FOUND, ERR_INVALID_INPUT


def stamp_create(row: dict, with_version: bool = True) -> dict:
    """Stamp id/created_at/updated_at/version on a brand-new row."""
    now = clock.iso()
    row.setdefault("id", db.new_id())
    row["created_at"] = now
    if with_version:
        row["updated_at"] = now
        row["version"] = 0
    return row


def stamp_create_appendonly(row: dict) -> dict:
    """Append-only row (FloorPlanVersion, SafetyInspection, AuditLogEntry): only id+created_at."""
    row.setdefault("id", db.new_id())
    row["created_at"] = clock.iso()
    return row


def bump(row: dict):
    """Bump updated_at and version on a row mutation."""
    row["updated_at"] = clock.iso()
    row["version"] = int(row.get("version", 0)) + 1


def check_occ(row: dict, request_body):
    """If request body provided `version`, compare to row.version. Mismatch → ERR_VERSION_CONFLICT."""
    if not isinstance(request_body, dict):
        return
    if "version" not in request_body:
        return
    supplied = request_body["version"]
    if supplied is None:
        return
    try:
        supplied_int = int(supplied)
    except (TypeError, ValueError):
        # Bad type for version field — treat as conflict
        raise AppError(ERR_VERSION_CONFLICT, "Invalid version value.", 409)
    if supplied_int != int(row.get("version", 0)):
        raise AppError(ERR_VERSION_CONFLICT, "Version mismatch.", 409)


def must_exist(table: dict, resource_id: str, label: str = "resource"):
    """Fetch a row by id or raise ERR_NOT_FOUND."""
    row = table.get(resource_id)
    if row is None:
        raise AppError(ERR_NOT_FOUND, f"{label} not found.", 404)
    return row


def must_dict(body):
    """Require the JSON body to be a (possibly empty) dict."""
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise AppError(ERR_INVALID_INPUT, "Request body must be a JSON object.", 422)
    return body


def write_audit(subject_kind: str, subject_id: str, action: str, payload: dict | None = None) -> dict:
    """Append an AuditLogEntry."""
    entry = stamp_create_appendonly({
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "action": action,
        "actor_role": getattr(g, "role", None),
        "actor_id": getattr(g, "user_id", None),
        "payload": payload or {},
    })
    db.audit_logs[entry["id"]] = entry
    return entry


def serialize(row: dict) -> dict:
    """Return a deep copy of a row for response (defensive)."""
    return deepcopy(row)


def get_exhibition_for_resource(resource: dict) -> dict | None:
    eid = resource.get("exhibition_id")
    if not eid:
        return None
    return db.exhibitions.get(eid)
