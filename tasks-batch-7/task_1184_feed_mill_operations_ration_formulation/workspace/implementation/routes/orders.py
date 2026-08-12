"""Customer orders: quote, confirm, revision loop, cancel, complete (PRD 3.5)."""
from flask import Blueprint, request

from db import STORE, make_record, bump, clock_now
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize
from services import (ser_order, sorted_items, credit_used, quote_stale, order_blocked,
                      order_price_quoted, order_price_final, batch_actual_tons,
                      ORDER_QTY_TOLERANCE)
from validation import get_body, req_str, req_tons, req_int, paginate

bp = Blueprint("orders", __name__)

D_ZERO_TONS_BATCHES = ("PLANNED", "BATCHING", "MIXED", "HOLD")


def _get_order_scoped(oid, role, uid):
    o = STORE["orders"].get(oid)
    # Customer-role callers see only their own orders; a foreign id is NOT_FOUND.
    if o is None or (role == "Customer" and o["customer_id"] != uid):
        raise ApiError("ERR_NOT_FOUND", 404, f"Order {oid} not found")
    return o


def _is_medicated(lines):
    for line in lines:
        ing = STORE["ingredients"].get(line["ingredient_id"])
        if ing is not None and ing["hazard_class"] == "MEDICATED":
            return True
    return False


def _permit_gate(customer, is_medicated):
    if is_medicated and customer["medicated_permit_ref"] is None:
        raise ApiError("ERR_MEDICATED_PERMIT_REQUIRED", 422,
                       "Medicated order requires a permit reference on file")


def _credit_gate(customer, quoted_total):
    if credit_used(customer["id"]) + quoted_total > customer["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                       "Order would exceed the customer's credit limit")


@bp.post("/api/orders")
def create_order():
    uid, role = authenticate()
    data = get_body()
    formula_id = req_str(data, "formula_id")
    tons = req_tons(data, "tons")
    expected = req_int(data, "expected_customer_version")
    authorize(role, uid, {"Customer"})
    # customer_id is taken from X-User-ID, never from the payload (PRD 3.5).
    customer = STORE["customers"].get(uid)
    if customer is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Customer {uid} not found")
    formula = STORE["formulas"].get(formula_id)
    if formula is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Formula {formula_id} not found")
    if expected != customer["version"]:
        raise ApiError("ERR_STALE_CUSTOMER_VERSION", 412,
                       "expected_customer_version does not match the customer's version")
    if formula["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Orders may be placed only against ACTIVE formulas")
    T = clock_now()
    is_med = _is_medicated(formula["lines"])
    quoted_total = order_price_quoted(formula["lines"], tons, T, is_med)
    rec = make_record()
    rec.update(customer_id=uid, formula_id=formula_id, tons=tons, is_medicated=is_med,
               quoted_formula_version=formula["version"],
               quoted_cost_basis_cents=formula["provisional_cost_cents_per_ton"],
               quoted_total_cents=quoted_total, pinned_formula_version=None,
               pinned_lines=None, pinned_min_protein_pct=None,
               pinned_max_fiber_pct=None, final_total_cents=None, status="QUOTED")
    STORE["orders"][rec["id"]] = rec
    # Creating an order mutates the customer's credit posture (PRD 3.5).
    bump(customer)
    return success(ser_order(rec), 201)


@bp.get("/api/orders")
def list_orders():
    uid, role = authenticate()
    authorize(role, uid, {"MillManager", "Customer"})
    customer_id = request.args.get("customer_id")
    formula_id = request.args.get("formula_id")
    status = request.args.get("status")
    if role == "Customer":
        customer_id = uid  # forced to the caller
    items = sorted_items(STORE["orders"])
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if formula_id is not None:
        items = [o for o in items if o["formula_id"] == formula_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    page, meta = paginate(items)
    return success([ser_order(o) for o in page], 200, meta)


@bp.get("/api/orders/<oid>")
def get_order(oid):
    uid, role = authenticate()
    authorize(role, uid, {"MillManager", "Customer"})
    return success(ser_order(_get_order_scoped(oid, role, uid)), 200)


@bp.post("/api/orders/<oid>/confirm")
def confirm_order(oid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"Customer"})
    o = _get_order_scoped(oid, role, uid)
    customer = STORE["customers"][o["customer_id"]]
    # Gates in order (PRD 3.5): state, then safety, then fiscal.
    if o["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a QUOTED order can be confirmed")
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Customer is not ACTIVE")
    _permit_gate(customer, o["is_medicated"])
    if quote_stale(o):
        raise ApiError("ERR_QUOTE_STALE", 409,
                       "The formula advanced since the quote; re-quote before confirming")
    _credit_gate(customer, o["quoted_total_cents"])
    formula = STORE["formulas"][o["formula_id"]]
    o["pinned_formula_version"] = formula["version"]
    o["pinned_lines"] = [dict(l) for l in formula["lines"]]
    o["pinned_min_protein_pct"] = formula["min_protein_pct"]
    o["pinned_max_fiber_pct"] = formula["max_fiber_pct"]
    o["status"] = "CONFIRMED"
    bump(o)
    bump(customer)
    return success(ser_order(o), 200)


@bp.post("/api/orders/<oid>/begin-revision")
def begin_revision(oid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"Customer"})
    o = _get_order_scoped(oid, role, uid)
    if o["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a CONFIRMED order can begin revision")
    if any(b["order_id"] == oid and b["status"] in ("BATCHING", "MIXED", "HOLD")
           for b in STORE["batches"].values()):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "A batch of this order is BATCHING, MIXED, or HOLD")
    o["status"] = "REVISING"
    bump(o)
    bump(STORE["customers"][o["customer_id"]])
    return success(ser_order(o), 200)


@bp.post("/api/orders/<oid>/commit-revision")
def commit_revision(oid):
    uid, role = authenticate()
    data = get_body()
    tons = req_tons(data, "tons")
    authorize(role, uid, {"Customer"})
    o = _get_order_scoped(oid, role, uid)
    if o["status"] != "REVISING":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a REVISING order can commit revision")
    customer = STORE["customers"][o["customer_id"]]
    # Re-quote at current prices against the current formula (PRD 3.5).
    T = clock_now()
    formula = STORE["formulas"][o["formula_id"]]
    is_med = _is_medicated(formula["lines"])
    new_quoted = order_price_quoted(formula["lines"], tons, T, is_med)
    _permit_gate(customer, is_med)
    _credit_gate(customer, new_quoted)
    o["tons"] = tons
    o["is_medicated"] = is_med
    o["quoted_total_cents"] = new_quoted
    o["quoted_formula_version"] = formula["version"]
    o["quoted_cost_basis_cents"] = formula["provisional_cost_cents_per_ton"]
    o["pinned_formula_version"] = formula["version"]
    o["pinned_lines"] = [dict(l) for l in formula["lines"]]
    o["pinned_min_protein_pct"] = formula["min_protein_pct"]
    o["pinned_max_fiber_pct"] = formula["max_fiber_pct"]
    o["status"] = "CONFIRMED"
    bump(o)
    bump(customer)
    return success(ser_order(o), 200)


@bp.post("/api/orders/<oid>/cancel")
def cancel_order(oid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"Customer", "MillManager"})
    o = _get_order_scoped(oid, role, uid)
    if o["status"] in ("QUOTED", "REVISING"):
        o["status"] = "CANCELLED"
        bump(o)
        return success(ser_order(o), 200)
    if o["status"] == "CONFIRMED":
        if any(b["order_id"] == oid and b["status"] in D_ZERO_TONS_BATCHES
               for b in STORE["batches"].values()):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "A non-terminal batch blocks cancellation")
        if any(t["order_id"] == oid and t["status"] in ("PLANNED", "LOADING", "IN_TRANSIT")
               for t in STORE["trips"].values()):
            raise ApiError("ERR_INVALID_STATE", 409,
                           "A non-terminal delivery trip blocks cancellation")
        o["status"] = "CANCELLED"
        bump(o)
        bump(STORE["customers"][o["customer_id"]])  # credit exposure released
        return success(ser_order(o), 200)
    raise ApiError("ERR_INVALID_STATE", 409, f"An order in {o['status']} cannot be cancelled")


@bp.post("/api/orders/<oid>/complete")
def complete_order(oid):
    uid, role = authenticate()
    get_body()
    authorize(role, uid, {"MillManager"})
    o = _get_order_scoped(oid, role, uid)
    if o["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", 409, "Only an IN_PRODUCTION order can be completed")
    if order_blocked(oid):
        raise ApiError("ERR_ORDER_BLOCKED", 409, "A batch of this order is in HOLD")
    if any(b["order_id"] == oid and b["status"] in D_ZERO_TONS_BATCHES
           for b in STORE["batches"].values()):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Batches remain in PLANNED, BATCHING, MIXED, or HOLD")
    released = sum((batch_actual_tons(b["id"]) for b in STORE["batches"].values()
                    if b["order_id"] == oid and b["status"] == "RELEASED"), o["tons"] * 0)
    deviation = abs(released - o["tons"]) / o["tons"]
    if deviation > ORDER_QTY_TOLERANCE:
        raise ApiError("ERR_ORDER_TONS_MISMATCH", 422,
                       "Released tonnage deviates more than 2% from the order")
    o["final_total_cents"] = order_price_final(o)
    o["status"] = "COMPLETED"
    bump(o)
    bump(STORE["customers"][o["customer_id"]])  # exposure reclasses quoted -> final
    return success(ser_order(o), 200)
