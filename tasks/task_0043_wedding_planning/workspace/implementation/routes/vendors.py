"""Vendor and Quote routes."""
from flask import Blueprint, request, g

import db
from errors import (
    raise_error,
    ERR_VENDOR_NOT_APPROVED,
    ERR_QUOTE_EXPIRED,
)
from middleware import require_roles, check_vendor_rep_owns_vendor
from response import success, list_response, parse_pagination
from services.lookup import get_vendor, get_quote


bp = Blueprint("vendors", __name__)


@bp.post("/vendors")
def create_vendor():
    require_roles("VendorRep")
    body = request.get_json(silent=True) or {}
    vendor = {
        "name": body.get("name"),
        "category": body.get("category"),
        "qualification_status": "PENDING_REVIEW",
        "avg_performance_rating": None,
        "rating_count": 0,
    }
    db.add_common_create(vendor)
    db.vendors[vendor["id"]] = vendor
    return success(vendor, status=201)


@bp.get("/vendors")
def list_vendors():
    require_roles("Planner", "Auditor", "VendorRep")
    limit, offset = parse_pagination(request.args)
    cat = request.args.get("category")
    qs = request.args.get("qualification_status")
    items = list(db.vendors.values())
    if cat:
        items = [v for v in items if v["category"] == cat]
    if qs:
        items = [v for v in items if v["qualification_status"] == qs]
    items.sort(key=lambda v: v["created_at"])
    return list_response(items, limit, offset)


@bp.get("/vendors/<vendor_id>")
def get_vendor_route(vendor_id):
    require_roles("Planner", "Auditor", "VendorRep")
    v = get_vendor(vendor_id)
    return success(v)


def _vendor_status_transition(vendor_id, allowed_from, new_status):
    require_roles("Auditor")
    v = get_vendor(vendor_id)
    if v["qualification_status"] not in allowed_from:
        # No specific error in catalog for vendor transitions; reuse generic state error.
        # The PRD states transitions are auditor-driven; we'll surface a 409 with ERR_VENDOR_NOT_APPROVED
        # only if relevant, else use a 409 catch-all. Use ERR_VENDOR_NOT_APPROVED for non-APPROVED suspends.
        from errors import APIError
        if new_status == "SUSPENDED":
            raise APIError(ERR_VENDOR_NOT_APPROVED, 422, "Vendor must be APPROVED")
        raise APIError("ERR_VENDOR_NOT_APPROVED", 422, "Invalid vendor state transition")
    v["qualification_status"] = new_status
    db.bump(v)
    return v


@bp.post("/vendors/<vendor_id>/approve")
def approve_vendor(vendor_id):
    v = _vendor_status_transition(vendor_id, ("PENDING_REVIEW",), "APPROVED")
    return success(v)


@bp.post("/vendors/<vendor_id>/reject")
def reject_vendor(vendor_id):
    v = _vendor_status_transition(vendor_id, ("PENDING_REVIEW",), "REJECTED")
    return success(v)


@bp.post("/vendors/<vendor_id>/suspend")
def suspend_vendor(vendor_id):
    v = _vendor_status_transition(vendor_id, ("APPROVED",), "SUSPENDED")
    # Cascade quotes DRAFT/OFFERED -> WITHDRAWN
    for q in db.quotes.values():
        if q["vendor_id"] == vendor_id and q["status"] in ("DRAFT", "OFFERED"):
            q["status"] = "WITHDRAWN"
            db.bump(q)
    return success(v)


@bp.post("/vendors/<vendor_id>/reinstate")
def reinstate_vendor(vendor_id):
    v = _vendor_status_transition(vendor_id, ("SUSPENDED",), "APPROVED")
    return success(v)


# --- Quotes ---


@bp.post("/vendors/<vendor_id>/quotes")
def create_quote(vendor_id):
    require_roles("VendorRep")
    v = get_vendor(vendor_id)
    check_vendor_rep_owns_vendor(v)
    body = request.get_json(silent=True) or {}
    quote = {
        "vendor_id": vendor_id,
        "category": v["category"],
        "amount_cents": int(body.get("amount_cents", 0)),
        "scope_description": body.get("scope_description"),
        "valid_until": int(body.get("valid_until")) if body.get("valid_until") is not None else None,
        "status": "DRAFT",
    }
    db.add_common_create(quote)
    db.quotes[quote["id"]] = quote
    return success(quote, status=201)


@bp.get("/vendors/<vendor_id>/quotes")
def list_quotes(vendor_id):
    require_roles("Planner", "Auditor", "VendorRep")
    get_vendor(vendor_id)
    limit, offset = parse_pagination(request.args)
    status_q = request.args.get("status")
    items = [q for q in db.quotes.values() if q["vendor_id"] == vendor_id]
    if status_q:
        items = [q for q in items if q["status"] == status_q]
    items.sort(key=lambda q: q["created_at"])
    return list_response(items, limit, offset)


@bp.post("/vendors/<vendor_id>/quotes/<quote_id>/offer")
def offer_quote(vendor_id, quote_id):
    require_roles("VendorRep")
    v = get_vendor(vendor_id)
    check_vendor_rep_owns_vendor(v)
    q = get_quote(vendor_id, quote_id)
    # State precondition first per priority order
    from errors import ERR_QUOTE_NOT_AVAILABLE
    if q["status"] != "DRAFT":
        raise_error(ERR_QUOTE_NOT_AVAILABLE, "Quote must be DRAFT to be offered")
    # Vendor must be approved (priority 7 referential)
    if v["qualification_status"] != "APPROVED":
        raise_error(ERR_VENDOR_NOT_APPROVED, "Vendor not approved")
    if db.now_clock() >= int(q["valid_until"]):
        raise_error(ERR_QUOTE_EXPIRED, "Quote has expired")
    q["status"] = "OFFERED"
    db.bump(q)
    return success(q)


@bp.post("/vendors/<vendor_id>/quotes/<quote_id>/withdraw")
def withdraw_quote(vendor_id, quote_id):
    require_roles("VendorRep")
    v = get_vendor(vendor_id)
    check_vendor_rep_owns_vendor(v)
    q = get_quote(vendor_id, quote_id)
    from errors import ERR_QUOTE_NOT_AVAILABLE
    if q["status"] != "DRAFT":
        raise_error(ERR_QUOTE_NOT_AVAILABLE, "Quote must be DRAFT to withdraw via this endpoint")
    q["status"] = "WITHDRAWN"
    db.bump(q)
    return success(q)
