"""Auth header extraction, RBAC checks, body/field validation helpers."""

import re
from datetime import datetime

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
)

ROLES = (
    "ComplianceAnalyst",
    "ComplianceManager",
    "TradeOpsSpecialist",
    "ComplianceDirector",
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def auth(*allowed_roles):
    """Priority 1 (authentication) then priority 2 (authorization)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid == "" or role is None or role == "":
        raise ApiError(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header", 401)
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Unknown X-User-Role: %s" % role, 401)
    if allowed_roles and role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN,
            "Role %s is not permitted to call this endpoint" % role,
            403,
        )
    return uid, role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_VALIDATION, "Request body must be a JSON object", 400)
    return body


def find(store, entity_id, label="Resource"):
    entity = store.get(entity_id)
    if entity is None:
        raise ApiError(ERR_NOT_FOUND, "%s not found: %s" % (label, entity_id), 404)
    return entity


def check_body_fks(body, fk_map):
    """Priority-3 existence check for body-supplied FK references.

    fk_map: iterable of (field_name, store). Only well-typed (string) refs are
    checked here; type errors surface as ERR_VALIDATION at priority 4.
    """
    for field, store in fk_map:
        ref = body.get(field)
        if isinstance(ref, str) and ref not in store:
            raise ApiError(ERR_NOT_FOUND, "Referenced %s not found: %s" % (field, ref), 404)


def no_unknown(body, allowed):
    for key in body:
        if key not in allowed:
            raise ApiError(
                ERR_VALIDATION,
                "Unknown, computed, or system-managed field in body: %s" % key,
                400,
            )


def need(body, name):
    value = body.get(name, None)
    if value is None:
        raise ApiError(ERR_VALIDATION, "Missing required field: %s" % name, 400)
    return value


def v_str(value, name):
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, "Field %s must be a string" % name, 400)
    return value


def v_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_VALIDATION, "Field %s must be an integer" % name, 400)
    return value


def v_num(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_VALIDATION, "Field %s must be a number" % name, 400)
    return value


def v_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError(ERR_VALIDATION, "Field %s must be a boolean" % name, 400)
    return value


def v_enum(value, name, options):
    if not isinstance(value, str) or value not in options:
        raise ApiError(
            ERR_VALIDATION,
            "Field %s must be one of %s" % (name, ", ".join(sorted(options))),
            400,
        )
    return value


def v_date(value, name):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ApiError(ERR_VALIDATION, "Field %s must be a YYYY-MM-DD date" % name, 400)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ApiError(ERR_VALIDATION, "Field %s must be a valid calendar date" % name, 400)
    return value


def page_params():
    """Pagination parameters: limit (default 10, min 1, max 100), offset (default 0)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, "limit must be an integer", 400)
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, "limit must be between 1 and 100", 400)
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_VALIDATION, "offset must be >= 0", 400)
    return limit, offset


def filtered_sorted(store, filters):
    """Exact-match filters then created_at ASC (insertion order tie-break)."""
    import db

    items = list(store.values())
    for field, value in filters.items():
        if value is not None:
            items = [e for e in items if e.get(field) == value]
    items.sort(key=db.sort_key)
    return items
