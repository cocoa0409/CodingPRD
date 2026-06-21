"""Request-body field validation and resource lookup helpers.

Validation ordering follows PRD §2.9. Per-handler code performs auth → RBAC →
ownership → path existence → FK resolution → state → OCC → business gates →
fiscal → field validity in that order; the helpers here are the field-level and
lookup primitives those handlers call.
"""
from flask import request

from errors import (
    err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_FK_NOT_FOUND,
)
from db import db


# ---------------------------------------------------------------------------
# body parsing
# ---------------------------------------------------------------------------
def get_json_body():
    """Parse the JSON body; tolerate an empty body as {}."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# field-level validity (ERR_INVALID_REQUEST, lowest priority — PRD §2.9)
# ---------------------------------------------------------------------------
def require(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or not v.strip():
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a string")
    return v


def require_int(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return v


def opt_int(body, field, default=0):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    return v


def require_number(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a number")
    return v


def require_positive_int(body, field):
    v = require_int(body, field)
    if v <= 0:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be greater than zero")
    return v


def require_positive_number(body, field):
    v = require_number(body, field)
    if v <= 0:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be greater than zero")
    return v


def require_enum(body, field, allowed):
    v = require(body, field)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return v


def require_nonneg_int(body, field):
    v = require_int(body, field)
    if v < 0:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must not be negative")
    return v


# ---------------------------------------------------------------------------
# path existence (ERR_NOT_FOUND — PRD §2.6)
# ---------------------------------------------------------------------------
def get_or_404(collection, resource_id):
    entity = collection.get(resource_id)
    if entity is None:
        raise err(ERR_NOT_FOUND, "Resource not found")
    return entity


# ---------------------------------------------------------------------------
# body FK resolution scoped to a winery (ERR_FK_NOT_FOUND — PRD §2.6)
# ---------------------------------------------------------------------------
def resolve_fk(collection, fk_id, winery_id):
    """Resolve a body FK and require it belong to the same winery."""
    entity = collection.get(fk_id)
    if entity is None:
        raise err(ERR_FK_NOT_FOUND, "Referenced resource not found")
    if entity.get("winery_id") != winery_id:
        raise err(ERR_FK_NOT_FOUND, "Referenced resource belongs to a different winery")
    return entity


def resolve_winery_fk(winery_id):
    winery = db.wineries.get(winery_id)
    if winery is None:
        raise err(ERR_FK_NOT_FOUND, "Referenced winery not found")
    return winery
