"""Quote endpoints."""
from flask import Blueprint, request

import clock
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_QUOTE_EMPTY, ERR_NO_CERTIFIED_OPERATOR, ERR_QUOTE_EXPIRED,
    ERR_CREDIT_LIMIT_EXCEEDED, ERR_UNIT_NOT_LISTED,
)
from util import (
    body_json, req_str, req_int, opt_str, req_datetime, parse_iso_datetime,
    new_record, new_child_record, bump, success_object, list_response, get_or_404,
)
import services

bp = Blueprint("quotes", __name__)


@bp.post("/fleet/quotes")
def create_quote():
    _, role = authenticate()
    authorize(role, ["SalesRep"])
    body = body_json()
    customer_id = req_str(body, "customer_id")
    kind = req_str(body, "kind")
    if kind not in ("NEW_CONFIG", "USED_UNIT_SALE"):
        raise_err(ERR_INVALID_REQUEST, "kind must be NEW_CONFIG or USED_UNIT_SALE")
    unit_id = body.get("unit_id")
    if kind == "USED_UNIT_SALE":
        if not isinstance(unit_id, str):
            raise_err(ERR_INVALID_REQUEST, "unit_id is required for USED_UNIT_SALE")
    else:
        if unit_id is not None:
            raise_err(ERR_INVALID_REQUEST, "unit_id must be null for NEW_CONFIG")
    valid_until_raw = req_str(body, "valid_until")
    valid_until = parse_iso_datetime(valid_until_raw)
    if valid_until is None:
        raise_err(ERR_INVALID_REQUEST, "valid_until must be an ISO 8601 datetime")
    # existence: customer (and unit when used)
    customer = get_or_404(store.customers, customer_id, "Customer")
    if kind == "USED_UNIT_SALE":
        get_or_404(store.units, unit_id, "Unit")
    rec = new_record()
    rec.update({
        "customer_id": customer_id,
        "kind": kind,
        "unit_id": unit_id,
        "valid_until": valid_until,
        "status": "DRAFT",
        "submitted_at": None,
        "revision_count": 0,
        "subtotal_cents": 0,
        "discount_cents": 0,
        "tax_cents": 0,
        "total_cents": 0,
    })
    store.quotes[rec["id"]] = rec
    return success_object(services.serialize_quote(rec), 201)


@bp.get("/fleet/quotes/<qid>")
def get_quote(qid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    q = get_or_404(store.quotes, qid, "Quote")
    return success_object(services.serialize_quote(q), 200)


@bp.get("/fleet/quotes")
def list_quotes():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    records = list(store.quotes.values())
    customer_id = request.args.get("customer_id")
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")
    if customer_id:
        records = [q for q in records if q["customer_id"] == customer_id]
    if unit_id:
        records = [q for q in records if q["unit_id"] == unit_id]
    if status:
        records = [q for q in records if q["status"] == status]
    return list_response(records, services.serialize_quote)


@bp.post("/fleet/quotes/<qid>/lines")
def add_quote_line(qid):
    _, role = authenticate()
    authorize(role, ["SalesRep"])
    body = body_json()
    description = req_str(body, "description")
    qty = req_int(body, "qty")
    unit_price = req_int(body, "unit_price_cents")
    if qty < 1:
        raise_err(ERR_INVALID_REQUEST, "qty must be >= 1")
    if unit_price < 0:
        raise_err(ERR_INVALID_REQUEST, "unit_price_cents must be >= 0")
    q = get_or_404(store.quotes, qid, "Quote")
    if q["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Lines may be added only while quote is DRAFT")
    rec = new_child_record()
    rec.update({
        "quote_id": q["id"],
        "description": description,
        "qty": qty,
        "unit_price_cents": unit_price,
        "extended_cents": qty * unit_price,
    })
    store.quote_lines[rec["id"]] = rec
    services.recompute_quote_pricing(q)
    bump(q)
    return success_object(services.serialize_quote_line(rec), 201)


@bp.get("/fleet/quotes/<qid>/lines")
def list_quote_lines(qid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    q = get_or_404(store.quotes, qid, "Quote")
    lines = [l for l in store.quote_lines.values() if l["quote_id"] == q["id"]]
    return list_response(lines, services.serialize_quote_line)


@bp.post("/fleet/quotes/<qid>/submit")
def submit_quote(qid):
    _, role = authenticate()
    authorize(role, ["SalesRep"])
    q = get_or_404(store.quotes, qid, "Quote")
    if q["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Quote must be DRAFT to submit")
    lines = [l for l in store.quote_lines.values() if l["quote_id"] == q["id"]]
    if not lines:
        raise_err(ERR_QUOTE_EMPTY, "Quote has zero lines")
    q["status"] = "SUBMITTED"
    q["submitted_at"] = clock.now()
    bump(q)
    return success_object(services.serialize_quote(q), 200)


@bp.post("/fleet/quotes/<qid>/revise")
def revise_quote(qid):
    _, role = authenticate()
    authorize(role, ["SalesRep"])
    q = get_or_404(store.quotes, qid, "Quote")
    if q["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Quote must be SUBMITTED to revise")
    q["status"] = "DRAFT"
    q["revision_count"] = q.get("revision_count", 0) + 1
    q["submitted_at"] = None
    bump(q)
    return success_object(services.serialize_quote(q), 200)


@bp.post("/fleet/quotes/<qid>/accept")
def accept_quote(qid):
    _, role = authenticate()
    authorize(role, ["SalesRep"])
    q = get_or_404(store.quotes, qid, "Quote")
    if q["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Quote must be SUBMITTED to accept")
    customer = get_or_404(store.customers, q["customer_id"], "Customer")
    # certified operator requirement
    if not services.customer_has_active_certified_operator(customer["id"]):
        raise_err(ERR_NO_CERTIFIED_OPERATOR, "Customer has no operator holding an ACTIVE certification")
    # quote expiry
    if clock.now() > q["valid_until"]:
        raise_err(ERR_QUOTE_EXPIRED, "Quote has passed valid_until")
    # used-unit sale: unit must be LISTED (PRD §3.2: ERR_UNIT_NOT_LISTED)
    unit = None
    if q["kind"] == "USED_UNIT_SALE":
        unit = get_or_404(store.units, q["unit_id"], "Unit")
        if unit["availability_status"] != "LISTED":
            raise_err(ERR_UNIT_NOT_LISTED, "Referenced unit is not LISTED")
    # credit fit
    if q["total_cents"] > services.customer_available_credit(customer):
        raise_err(ERR_CREDIT_LIMIT_EXCEEDED, "Quote total exceeds available credit")
    q["status"] = "ACCEPTED"
    bump(q)
    services.post_charge_to_customer(customer, q["total_cents"])
    bump(customer)
    if unit is not None:
        unit["availability_status"] = "SOLD"
        bump(unit)
    return success_object(services.serialize_quote(q), 200)
