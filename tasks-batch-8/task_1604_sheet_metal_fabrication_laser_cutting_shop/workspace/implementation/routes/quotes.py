"""Quote lifecycle endpoints: create, lines, price (OCC), submit, revise, accept, reject."""
from datetime import timedelta
from flask import Blueprint

import db
from db import store, new_id, touch, new_common, iso_logical
from errors import ApiError
from response import ok, created, paginate
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity, resolve_fk, LINE_SCHEMA
from services.audit import audit
from services.pricing import (
    add_line, quote_lines, reprice_line, recompute_quote_totals, recompute_committed,
    run_expiry_sweep, validate_line, QUOTE_VALIDITY_DAYS,
)
from services.nesting import simulate_nest, apply_nest
from services.routing import (
    required_stations, assign_machines, generate_routing, recompute_order_due,
)

bp = Blueprint("quotes", __name__)

READ_ROLES = ["ShopManager", "Estimator", "ProductionPlanner", "CustomerRep"]
ESTIMATOR = ["Estimator"]
REP = ["CustomerRep"]


def _quote_or_404(quote_id):
    return require_path_entity(store.quotes, quote_id)


def _own_or_404(quote, uid, role):
    if role == "CustomerRep" and quote["customer_id"] != uid:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")


@bp.post("/fab/quotes")
def create_quote():
    uid, role, _ = get_context()
    require_roles(ESTIMATOR)
    body = parse_body({
        "customer_id": ("string", True, None),
        "expedite_tier": ("enum", False, ["STANDARD", "EXPEDITE", "RUSH"]),
        "lines": ("lines", False, None),
    }, allow_empty=False)
    customer = resolve_fk(store.customers, body["customer_id"], "customer_id")
    quote = {
        "id": new_id(),
        "customer_id": customer["id"],
        "expedite_tier": body.get("expedite_tier", "STANDARD"),
        "status": "DRAFT",
        "quoted_subtotal_cents": 0,
        "quoted_expedite_cents": 0,
        "quoted_total_cents": 0,
        "submitted_at": None,
        "expires_at": None,
        "revision_count": 0,
        "_submitted_dt": None,
        "_expires_dt": None,
    }
    new_common(quote)
    for spec in body.get("lines", []):
        add_line(quote, spec)
    store.quotes[quote["id"]] = quote
    return created(quote)


@bp.get("/fab/quotes")
def list_quotes():
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    run_expiry_sweep()
    rows = list(store.quotes.values())
    if role == "CustomerRep":
        rows = [q for q in rows if q["customer_id"] == uid]
    for f in ("customer_id", "status"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/fab/quotes/<quote_id>")
def get_quote(quote_id):
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    run_expiry_sweep()
    q = _quote_or_404(quote_id)
    _own_or_404(q, uid, role)
    return ok(q)


@bp.post("/fab/quotes/<quote_id>/lines")
def add_line_route(quote_id):
    uid, role, _ = get_context()
    require_roles(ESTIMATOR)
    body = parse_body(LINE_SCHEMA, allow_empty=False)
    q = _quote_or_404(quote_id)
    if q["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Lines may be added only while the quote is DRAFT")
    line = add_line(q, body)
    return created(line)


@bp.get("/fab/quotes/<quote_id>/lines")
def list_quote_lines(quote_id):
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    q = _quote_or_404(quote_id)
    _own_or_404(q, uid, role)
    return ok(paginate(quote_lines(q["id"])), rtype="array", pagination=paginate)


@bp.get("/fab/quote-lines")
def list_all_lines():
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    rows = list(store.quote_lines.values())
    if role == "CustomerRep":
        rows = [l for l in rows
                if store.quotes.get(l["quote_id"]) and store.quotes[l["quote_id"]]["customer_id"] == uid]
    for f in ("quote_id", "grade_id", "status"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/fab/quote-lines/<line_id>")
def get_line(line_id):
    uid, role, _ = get_context()
    require_roles(READ_ROLES)
    line = require_path_entity(store.quote_lines, line_id)
    if role == "CustomerRep":
        q = store.quotes.get(line["quote_id"])
        if q is None or q["customer_id"] != uid:
            raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return ok(line)


@bp.post("/fab/quotes/<quote_id>/price")
def price_quote(quote_id):
    uid, role, _ = get_context()
    require_roles(ESTIMATOR)
    body = parse_body({"expected_quote_version": ("integer", True, None)}, allow_empty=False)
    q = _quote_or_404(quote_id)
    # state tier first
    if q["status"] != "DRAFT":
        raise ApiError("ERR_QUOTE_NOT_OPEN", 409, "Pricing requires the quote to be DRAFT")
    lines = [l for l in quote_lines(q["id"]) if l["status"] in ("ESTIMATED", "PRICED")]
    if not lines:
        raise ApiError("ERR_QUOTE_EMPTY", 409, "Pricing a quote with zero lines")
    # structural then finish compatibility, per line
    for line in lines:
        validate_line(q, line)
    # optimistic concurrency guard runs last
    if body["expected_quote_version"] != q["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Quote version has advanced since last read")
    for line in lines:
        reprice_line(q, line)
        line["status"] = "PRICED"
        touch(line)
    recompute_quote_totals(q)
    q["status"] = "PRICED"
    touch(q)
    audit("Quote", q["id"], "QUOTE_PRICED", role, uid,
          {"before": {"status": "DRAFT"}, "after": {"status": "PRICED"}})
    return ok(q)


@bp.post("/fab/quotes/<quote_id>/submit")
def submit_quote(quote_id):
    uid, role, _ = get_context()
    require_roles(ESTIMATOR)
    q = _quote_or_404(quote_id)
    if q["status"] != "PRICED":
        raise ApiError("ERR_QUOTE_NOT_PRICED", 409, "Submit requires the quote to be PRICED")
    customer = store.customers[q["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409, "Customer is SUSPENDED")
    now = db.LOGICAL_CLOCK
    expires = now + timedelta(days=QUOTE_VALIDITY_DAYS)
    q["_submitted_dt"] = now
    q["_expires_dt"] = expires
    q["submitted_at"] = iso_logical(now)
    q["expires_at"] = iso_logical(expires)
    q["status"] = "SUBMITTED"
    touch(q)
    audit("Quote", q["id"], "QUOTE_SUBMITTED", role, uid,
          {"before": {"status": "PRICED"}, "after": {"status": "SUBMITTED"}})
    return ok(q)


@bp.post("/fab/quotes/<quote_id>/revise")
def revise_quote(quote_id):
    uid, role, _ = get_context()
    require_roles(ESTIMATOR)
    q = _quote_or_404(quote_id)
    if q["status"] != "SUBMITTED":
        raise ApiError("ERR_QUOTE_NOT_OPEN", 409, "Revise requires the quote to be SUBMITTED")
    q["revision_count"] += 1
    q["_submitted_dt"] = None
    q["_expires_dt"] = None
    q["submitted_at"] = None
    q["expires_at"] = None
    q["status"] = "DRAFT"
    touch(q)
    for line in quote_lines(q["id"]):
        if line["status"] != "ESTIMATED":
            line["status"] = "ESTIMATED"
            touch(line)
    audit("Quote", q["id"], "QUOTE_REVISED", role, uid,
          {"before": {"status": "SUBMITTED"}, "after": {"status": "DRAFT",
                                                       "revision_count": q["revision_count"]}})
    return ok(q)


@bp.post("/fab/quotes/<quote_id>/accept")
def accept_quote(quote_id):
    uid, role, _ = get_context()
    require_roles(REP)
    q = _quote_or_404(quote_id)
    _own_or_404(q, uid, role)
    if q["status"] != "SUBMITTED":
        raise ApiError("ERR_QUOTE_NOT_OPEN", 409, "Accept requires the quote to be SUBMITTED")
    customer = store.customers[q["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 409, "Customer is SUSPENDED")
    if q["_expires_dt"] is not None and not db.LOGICAL_CLOCK < q["_expires_dt"]:
        raise ApiError("ERR_QUOTE_EXPIRED", 409, "Quote acceptance window has closed")

    lines = quote_lines(q["id"])
    pool = [s for s in store.sheet_stock.values() if s["status"] == "AVAILABLE"]
    stations = required_stations(lines)

    # validation cascade: machine capacity (tier 11) reported before nest
    # feasibility (tier 12) before the credit-limit fiscal guard (tier 14).
    nest_plan, nest_err = None, None
    try:
        nest_plan = simulate_nest(lines, pool)
    except ApiError as e:
        nest_err = e
    sheets_used = len(nest_plan) if nest_plan is not None else 0
    _, cap_err = assign_machines(stations, lines, sheets_used)
    if cap_err is not None:
        raise cap_err
    if nest_err is not None:
        raise nest_err

    open_total = sum(oq["quoted_total_cents"] for oq in store.quotes.values()
                     if oq["customer_id"] == customer["id"] and oq["status"] == "ACCEPTED")
    if open_total + q["quoted_total_cents"] > customer["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                       "Acceptance would exceed the customer's credit limit")

    # atomic accept cascade
    order = {
        "id": new_id(),
        "quote_id": q["id"],
        "customer_id": customer["id"],
        "expedite_tier": q["expedite_tier"],
        "status": "NESTING",
        "hold_reason": None,
        "committed_subtotal_cents": 0,
        "committed_total_cents": 0,
        "total_plate_area_cm2": 0,
        "scrap_credit_applied_cents": 0,
        "payment_status": "UNPAID",
        "paid_at": None,
        "completed_at": None,
        "due_date": None,
    }
    new_common(order)
    store.orders[order["id"]] = order
    apply_nest(order, nest_plan)
    order["status"] = "NESTED"
    recompute_committed(order, lines)
    generate_routing(order, lines, sheets_used, db.LOGICAL_CLOCK)
    recompute_order_due(order)
    touch(order)

    q["status"] = "ACCEPTED"
    touch(q)
    audit("Quote", q["id"], "QUOTE_ACCEPTED", role, uid,
          {"before": {"status": "SUBMITTED"}, "after": {"status": "ACCEPTED"}})
    audit("FabricationOrder", order["id"], "ORDER_CREATED", role, uid,
          {"after": {"status": "NESTED", "quote_id": q["id"]}})
    return created(order)


@bp.post("/fab/quotes/<quote_id>/reject")
def reject_quote(quote_id):
    uid, role, _ = get_context()
    require_roles(REP)
    q = _quote_or_404(quote_id)
    _own_or_404(q, uid, role)
    if q["status"] != "SUBMITTED":
        raise ApiError("ERR_QUOTE_NOT_OPEN", 409, "Reject requires the quote to be SUBMITTED")
    q["status"] = "REJECTED"
    touch(q)
    for line in quote_lines(q["id"]):
        if line["status"] in ("ESTIMATED", "PRICED"):
            line["status"] = "SUPERSEDED"
            touch(line)
    audit("Quote", q["id"], "QUOTE_REJECTED", role, uid,
          {"before": {"status": "SUBMITTED"}, "after": {"status": "REJECTED"}})
    return ok(q)
