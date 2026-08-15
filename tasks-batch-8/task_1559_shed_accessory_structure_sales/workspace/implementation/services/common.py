"""Shared helpers: entity construction, field validation, lookups."""

import re
import uuid

import db
from errors import invalid_request, not_found

MISSING = object()

_ENUMS = {
    "delivery_mode": {"PRE_BUILT", "ON_SITE_BUILD"},
    "foundation_type": {"GRAVEL_PAD", "CONCRETE_SLAB", "PIERS", "NONE"},
    "anchor_type": {"AUGER_STRAP", "NONE"},
    "purchase_type": {"CASH", "RTO"},
    "method": {"CASH", "CARD", "CHECK"},
    "option": {"WINDOW", "LOFT", "RAMP", "ELECTRICAL"},
    "order_status": {"DRAFT", "SITE_REVIEW", "PERMIT_REVIEW", "READY_TO_SCHEDULE",
                     "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CLOSED", "CANCELLED"},
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id() -> str:
    return str(uuid.uuid4())


def is_bool(v) -> bool:
    return isinstance(v, bool)


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def is_str(v) -> bool:
    return isinstance(v, str)


def check_enum(value, allowed: set, field: str):
    if not is_str(value) or value not in allowed:
        raise invalid_request(f"Invalid enum member for {field}: {value!r}")


def check_iso_date(value, field: str):
    if not is_str(value) or not _DATE_RE.match(value):
        raise invalid_request(f"{field} must be an ISO date string (YYYY-MM-DD)")
    # Validate it is a real calendar date
    db.parse_iso(value + "T00:00:00Z")


def get_body():
    """Return the JSON request body as a dict ({} when absent)."""
    from flask import request
    if request.data is None or len(request.data) == 0:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise invalid_request("Request body must be valid JSON")
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object")
    return body


def require(body: dict, field: str, types, allow_none: bool = False):
    """Fetch a required field with type checking."""
    if field not in body:
        raise invalid_request(f"Missing required field: {field}")
    v = body[field]
    if allow_none and v is None:
        return None
    if not _type_ok(v, types):
        raise invalid_request(f"Malformed value for {field}")
    return v


def optional(body: dict, field: str, types, default=MISSING, allow_none: bool = False):
    """Fetch an optional field; returns default when absent."""
    if field not in body:
        if default is MISSING:
            return MISSING
        return default
    v = body[field]
    if allow_none and v is None:
        return None
    if not _type_ok(v, types):
        raise invalid_request(f"Malformed value for {field}")
    return v


def _type_ok(v, types) -> bool:
    if isinstance(types, tuple):
        return any(_type_ok(v, t) for t in types)
    if types == "str":
        return is_str(v)
    if types == "int":
        return is_int(v)
    if types == "num":
        return is_num(v)
    if types == "bool":
        return is_bool(v)
    if types == "array":
        return isinstance(v, list)
    return False


# ---------------------------------------------------------------------------
# Entity lookups
# ---------------------------------------------------------------------------

def get_jurisdiction(jid: str) -> dict:
    row = db.jurisdictions.get(jid)
    if row is None:
        raise not_found("Jurisdiction not found")
    return row


def get_model(mid: str) -> dict:
    row = db.models.get(mid)
    if row is None:
        raise not_found("StructureModel not found")
    return row


def get_customer(cid: str) -> dict:
    row = db.customers.get(cid)
    if row is None:
        raise not_found("Customer not found")
    return row


def get_order(oid: str) -> dict:
    row = db.orders.get(oid)
    if row is None:
        raise not_found("Order not found")
    return row


def get_assessment(aid: str) -> dict:
    row = db.site_assessments.get(aid)
    if row is None:
        raise not_found("SiteAssessment not found")
    return row


def get_permit_app(pid: str) -> dict:
    row = db.permit_applications.get(pid)
    if row is None:
        raise not_found("PermitApplication not found")
    return row


def get_rto_contract(rid: str) -> dict:
    row = db.rto_contracts.get(rid)
    if row is None:
        raise not_found("RtoContract not found")
    return row


def get_payment(pid: str) -> dict:
    row = db.payments.get(pid)
    if row is None:
        raise not_found("Payment not found")
    return row


def get_service_ticket(tid: str) -> dict:
    row = db.service_tickets.get(tid)
    if row is None:
        raise not_found("ServiceTicket not found")
    return row


def latest_assessment_for_order(order_id: str):
    """The most recently created SiteAssessment for an order, or None."""
    rows = [a for a in db.site_assessments.values() if a["order_id"] == order_id]
    if not rows:
        return None
    rows.sort(key=lambda a: a["created_at"])
    return rows[-1]


def latest_permit_app_for_order(order_id: str):
    """The most recently created PermitApplication for an order, or None."""
    rows = [p for p in db.permit_applications.values() if p["order_id"] == order_id]
    if not rows:
        return None
    rows.sort(key=lambda p: p["created_at"])
    return rows[-1]


def rto_contract_for_order(order_id: str):
    for r in db.rto_contracts.values():
        if r["order_id"] == order_id:
            return r
    return None


def paginate(query, items):
    """Parse limit/offset and return (limit, offset). Invalid values -> 400."""
    limit_raw = query.get("limit", None)
    offset_raw = query.get("offset", None)
    try:
        limit = 10 if limit_raw is None else int(limit_raw)
    except (TypeError, ValueError):
        raise invalid_request("limit must be an integer")
    try:
        offset = 0 if offset_raw is None else int(offset_raw)
    except (TypeError, ValueError):
        raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    return limit, offset
