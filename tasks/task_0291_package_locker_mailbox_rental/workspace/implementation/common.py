"""Shared helpers: mutation/touch, validation primitives, pagination, ownership."""
from flask import request, g

from db import db, now_iso
from errors import err
import constants as C

# Entities that carry updated_at + version (common_fields true).
VERSIONED = {
    "facilities", "locker_units", "mailbox_units", "customers", "forms_1583",
    "rental_agreements", "packages", "mail_items", "forwarding_requests",
    "invoices", "payments",
}


def touch(row):
    """Refresh updated_at and bump version on a mutated versioned row."""
    if "version" in row:
        row["version"] += 1
    if "updated_at" in row:
        row["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Request body parsing & field validation (ERR_INVALID_REQUEST, priority 4)
# ---------------------------------------------------------------------------
def get_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}")
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")
    return v


def optional_bool(body, field, default=False):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return v


# ---------------------------------------------------------------------------
# Existence (ERR_NOT_FOUND, priority 3)
# ---------------------------------------------------------------------------
def get_or_404(collection, _id):
    row = collection.get(_id)
    if row is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return row


def fk_or_404(collection, _id):
    """Validate a foreign key supplied in a body references an existing row."""
    if _id not in collection:
        raise err("ERR_NOT_FOUND", "Referenced resource not found")
    return collection[_id]


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_v < 1 or limit_v > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_v < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit_v, offset_v


def paginate(items, limit, offset):
    """Sort by created_at asc (insertion seq as tiebreak), then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Ownership (Customer role, PRD §2.1)
# ---------------------------------------------------------------------------
def owning_customer_of_agreement(agreement):
    return agreement.get("customer_id")


def agreement_of_mail_item(mail_item):
    return db.rental_agreements.get(mail_item["rental_agreement_id"])


def customer_owns(resource_customer_id):
    return g.role != "Customer" or g.user_id == resource_customer_id


def require_customer_owns(resource_customer_id):
    if g.role == "Customer" and g.user_id != resource_customer_id:
        raise err("ERR_FORBIDDEN", "Customer does not own this resource")
