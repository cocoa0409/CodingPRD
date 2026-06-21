"""Shared helpers: body parsing/validation, pagination, serialization, lookups."""

from flask import request

import db
from errors import (
    api_error,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_FK_NOT_FOUND,
)

# Public, serializable fields per entity (system fields appended by serialize()).
# Exemption and AuditEvent are append-only: id + created_at only (PRD §2.4).

_PUBLIC_FIELDS = {
    "Requester": ["full_name", "email", "organization", "declared_category", "outstanding_balance_cents"],
    "FoiaOfficer": ["full_name", "badge_id", "can_invoke_glomar"],
    "AppealAuthority": ["full_name", "badge_id"],
    "Submitter": ["company_name", "contact_email"],
    "FoiaRequest": [
        "requester_id", "assigned_officer_id", "subject_description", "fee_category",
        "expedited", "fee_waiver_requested", "fee_waiver_granted", "status",
        "deadline_status", "glomar_exemption_basis", "fee_payment_status", "received_at",
    ],
    "ResponsiveRecord": [
        "request_id", "title", "page_count", "contains_submitter_info",
        "submitter_id", "disposition",
    ],
    "Exemption": ["request_id", "record_id", "applies_to_kind", "exemption_code", "justification"],
    "FeeEstimate": [
        "request_id", "search_hours", "review_hours", "billable_pages",
        "assessed_fee_cents", "requires_advance_payment",
    ],
    "ProcessingDeadline": [
        "request_id", "base_due_at", "extension_days_added",
        "tolled_working_days", "effective_due_at",
    ],
    "Appeal": [
        "request_id", "appellant_id", "assigned_authority_id", "grounds",
        "status", "filed_at",
    ],
    "ThirdPartyObjection": [
        "record_id", "submitter_id", "notice_sent_at", "objection_text", "status",
    ],
    "ReadingRoom": ["name", "capacity"],
    "ReviewStation": ["name", "buffer_minutes"],
    "ReadingRoomBooking": ["room_id", "request_id", "starts_at", "ends_at"],
    "ReviewStationBooking": ["station_id", "request_id", "starts_at", "ends_at"],
    "AuditEvent": ["request_id", "event_type", "detail", "actor_role"],
}

_VERSIONED = {
    name for name in _PUBLIC_FIELDS if name not in ("Exemption", "AuditEvent")
}


def serialize(kind: str, obj: dict) -> dict:
    out = {"id": obj["id"]}
    for f in _PUBLIC_FIELDS[kind]:
        out[f] = obj.get(f)
    out["created_at"] = obj["created_at"]
    if kind in _VERSIONED:
        out["updated_at"] = obj["updated_at"]
        out["version"] = obj["version"]
    return out


# ---- Body parsing ----------------------------------------------------------
def get_json_body() -> dict:
    """Parse the JSON body, tolerating an empty body for no-input transitions."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise api_error(ERR_INVALID_REQUEST, "Request body must be valid JSON.")
    if not isinstance(body, dict):
        raise api_error(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require_fields(body: dict, fields):
    for f in fields:
        if body.get(f) is None:
            raise api_error(ERR_INVALID_REQUEST, f"Missing required field: {f}.")


def require_str(body: dict, field: str, *, non_empty: bool = True):
    v = body.get(field)
    if not isinstance(v, str) or (non_empty and v.strip() == ""):
        raise api_error(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string.")
    return v


def opt_str(body: dict, field: str):
    if field not in body or body[field] is None:
        return None
    v = body[field]
    if not isinstance(v, str):
        raise api_error(ERR_INVALID_REQUEST, f"Field {field} must be a string.")
    return v


def require_bool(body: dict, field: str, default=None):
    if field not in body or body[field] is None:
        if default is None:
            raise api_error(ERR_INVALID_REQUEST, f"Missing required field: {field}.")
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise api_error(ERR_INVALID_REQUEST, f"Field {field} must be a boolean.")
    return v


def require_int(body: dict, field: str, *, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise api_error(ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise api_error(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}.")
    return v


def require_number(body: dict, field: str, *, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise api_error(ERR_INVALID_REQUEST, f"Field {field} must be a number.")
    if minimum is not None and v < minimum:
        raise api_error(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}.")
    return v


def require_enum(body: dict, field: str, allowed):
    v = body.get(field)
    if v is None:
        raise api_error(ERR_INVALID_REQUEST, f"Missing required field: {field}.")
    if v not in allowed:
        raise api_error(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}.")
    return v


# ---- Existence / FK lookups -------------------------------------------------
def get_or_404(collection: dict, _id):
    """Path-referenced existence check -> ERR_NOT_FOUND (PRD §2.5)."""
    obj = collection.get(_id)
    if obj is None:
        raise api_error(ERR_NOT_FOUND, "Path-referenced resource does not exist.")
    return obj


def fk_or_404(collection: dict, _id):
    """Body FK existence check -> ERR_FK_NOT_FOUND (PRD §2.5)."""
    obj = collection.get(_id)
    if obj is None:
        raise api_error(ERR_FK_NOT_FOUND, "Body foreign key references a non-existent entity.")
    return obj


# ---- Pagination + list rendering (PRD §2.3) --------------------------------
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise api_error(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise api_error(ERR_INVALID_REQUEST, "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise api_error(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise api_error(ERR_INVALID_REQUEST, "offset must be >= 0.")
    return limit, offset


def sort_by_creation(items):
    """Ascending by created_at, then by internal sequence to break ties."""
    return sorted(items, key=lambda o: (o["created_at"], o.get("_seq", 0)))


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, total, has_more
