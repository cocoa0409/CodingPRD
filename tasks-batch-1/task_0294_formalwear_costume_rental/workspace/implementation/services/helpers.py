"""Shared request-parsing, validation, and pagination helpers."""
from flask import request

import db
from errors import (
    err,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
)

# Enum domains (SCAFFOLD §1.1)
CATEGORY_VALUES = {"FORMALWEAR", "COSTUME"}
SIZE_VALUES = {"XS", "S", "M", "L", "XL", "XXL"}
DISPOSITION_VALUES = {"CLEAN", "DAMAGED", "LOST"}
ALTERATION_KINDS = {"HEM", "TAKE_IN", "LET_OUT"}


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the request JSON body as a dict ({} when absent/empty)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def as_int_min(body, field, minimum, required=True, default=None):
    """Validate an integer field at/above a minimum. Bool is rejected as int."""
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}")
    return val


def as_enum(body, field, allowed, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field {field} has invalid value")
    return val


def as_str(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return val


def as_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a boolean")
    return val


# ---------------------------------------------------------------------------
# Existence lookups (left-to-right, ERR_NOT_FOUND on first miss)
# ---------------------------------------------------------------------------
_STORES = {
    "Catalog": "catalogs",
    "GarmentUnit": "garment_units",
    "Customer": "customers",
    "MeasurementProfile": "measurement_profiles",
    "Reservation": "reservations",
    "Alteration": "alterations",
    "PartyOrder": "party_orders",
    "Settlement": "settlements",
    "FitCheck": "fit_checks",
    "LedgerEntry": "ledger_entries",
}


def find(entity, entity_id):
    """Return the stored record or raise ERR_NOT_FOUND."""
    store = getattr(db, _STORES[entity])
    rec = store.get(entity_id)
    if rec is None:
        raise err(ERR_NOT_FOUND, f"{entity} not found")
    return rec


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------
def parse_pagination():
    limit = _parse_int_param("limit", default=10)
    offset = _parse_int_param("offset", default=0)
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    # Clamp to declared bounds.
    if limit < 1:
        limit = 1
    elif limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate_sorted(records, limit, offset):
    """Sort by created_at ASC (insertion seq tie-break) then page."""
    ordered = sorted(records, key=lambda r: (r["created_at"], db.seq_of(r)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
