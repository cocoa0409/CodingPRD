"""Musical Instrument Store API — Flask entry point.

In-memory only. Boots empty on every process start. No seeding/preloading.
"""

import os

from flask import Flask, request

import calc
import models as M
from auth import authenticate, require_role
from db import db
from errors import ApiError, err
from response import success, list_success, error_response
from validate import (
    get_body, require, opt, as_str, as_int, as_number, as_bool, as_enum,
    int_min, int_range, frac, parse_pagination, paginate,
)

app = Flask(__name__)

CATEGORIES = {"BAND", "ORCHESTRA", "GUITAR", "KEYBOARD", "OTHER"}
CONDITIONS = {"NEW", "USED", "VINTAGE"}
SOURCE_KINDS = {"STORE_PURCHASE", "TRADE_IN", "CONSIGNMENT"}
PLANS = {"RENTAL", "RENT_TO_OWN"}
TERM_MONTHS = {6, 12, 24, 36}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % str(e))


# ---------------------------------------------------------------------------
# Lookup helpers (existence; raise ERR_NOT_FOUND)
# ---------------------------------------------------------------------------

def lookup(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource %s not found" % rid)
    return rec


def get_customer(cid):
    return lookup(db.customers, cid)


def get_unit(uid):
    return lookup(db.units, uid)


def get_agreement(aid):
    return lookup(db.agreements, aid)


def get_layaway(lid):
    return lookup(db.layaway_plans, lid)


def get_repair(tid):
    return lookup(db.repair_tickets, tid)


def get_consignment(cid):
    return lookup(db.consignment_listings, cid)


def get_tradein(tid):
    return lookup(db.trade_ins, tid)


def get_financing(fid):
    return lookup(db.financing_applications, fid)


def get_special_order(oid):
    return lookup(db.special_orders, oid)


def get_lesson(eid):
    return lookup(db.lesson_enrollments, eid)


# ---------------------------------------------------------------------------
# Customer ownership enforcement (PRD §2.1)
# ---------------------------------------------------------------------------

def enforce_customer_owns(identity, owner_id):
    """When the caller is a Customer, they may only act on their own resources."""
    if identity.is_customer and identity.user_id != owner_id:
        raise err("ERR_FORBIDDEN", "Customer may only act on their own resources")


# ---------------------------------------------------------------------------
# Listing helper
# ---------------------------------------------------------------------------

def sorted_records(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def list_endpoint(records, serializer, identity, owner_field=None):
    """Apply pagination + sort by created_at asc. Optionally scope to the customer's
    own records when the caller is a Customer."""
    limit, offset = parse_pagination()
    items = list(records)
    if owner_field is not None and identity.is_customer:
        items = [r for r in items if r.get(owner_field) == identity.user_id]
    items = sorted_records(items)
    page, total = paginate(items, limit, offset)
    data = [serializer(r) for r in page]
    return list_success(data, limit, offset, total)


# ===========================================================================
# Logical clock
# ===========================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    identity = authenticate()
    require_role(identity, {"StoreManager"})
    body = get_body()
    to_iso = require(body, "to_iso8601")
    if not isinstance(to_iso, str):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be a string")
    try:
        db.clock.set_iso(to_iso)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 instant")
    return success({}, status=200)


# ===========================================================================
# Customer
# ===========================================================================

@app.route("/customers", methods=["POST"])
def create_customer():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager"})
    body = get_body()
    full_name = as_str(require(body, "full_name"), "full_name")
    email = as_str(require(body, "email"), "email")
    credit_score = int_range(require(body, "credit_score"), "credit_score", 300, 850)
    # email unique among customers (well-formedness/business constraint)
    for c in db.customers.values():
        if c["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email must be unique among customers")
    rec = M.new_common({
        "full_name": full_name,
        "email": email,
        "credit_score": credit_score,
        "store_credit_cents": 0,
    })
    db.customers[rec["id"]] = rec
    return success(M.ser_customer(rec), status=201)


@app.route("/customers/<customer_id>", methods=["GET"])
def get_customer_route(customer_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    rec = get_customer(customer_id)
    if identity.is_customer and identity.user_id != rec["id"]:
        raise err("ERR_FORBIDDEN", "Customer may only read their own record")
    return success(M.ser_customer(rec), status=200)


@app.route("/customers", methods=["GET"])
def list_customers():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager"})
    return list_endpoint(db.customers.values(), M.ser_customer, identity)


# ===========================================================================
# InventoryUnit
# ===========================================================================

@app.route("/units", methods=["POST"])
def create_unit():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager"})
    body = get_body()
    model_name = as_str(require(body, "model_name"), "model_name")
    category = as_enum(require(body, "category"), "category", CATEGORIES)
    condition = as_enum(require(body, "condition"), "condition", CONDITIONS)
    serial_number = as_str(require(body, "serial_number"), "serial_number")
    acquisition_cost_cents = int_min(require(body, "acquisition_cost_cents"), "acquisition_cost_cents", 0)
    list_price_cents = int_min(require(body, "list_price_cents"), "list_price_cents", 0)
    monthly_rent_cents = int_min(require(body, "monthly_rent_cents"), "monthly_rent_cents", 0)
    source_kind = as_enum(opt(body, "source_kind", "STORE_PURCHASE"), "source_kind", SOURCE_KINDS)

    # serial unique among units sharing the same model_name
    for u in db.units.values():
        if u["model_name"] == model_name and u["serial_number"] == serial_number:
            raise err("ERR_DUPLICATE_SERIAL", "serial_number already used for this model")

    unit = M.mint_unit(
        model_name, category, condition, serial_number, acquisition_cost_cents,
        list_price_cents, monthly_rent_cents, "AVAILABLE", source_kind,
    )
    return success(M.ser_unit(unit), status=201)


@app.route("/units/<unit_id>", methods=["GET"])
def get_unit_route(unit_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    rec = get_unit(unit_id)
    return success(M.ser_unit(rec), status=200)


@app.route("/units", methods=["GET"])
def list_units():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.units.values())
    status_f = request.args.get("status")
    category_f = request.args.get("category")
    cl_f = request.args.get("consignment_listing_id")
    if status_f is not None:
        items = [u for u in items if u["status"] == status_f]
    if category_f is not None:
        items = [u for u in items if u["category"] == category_f]
    if cl_f is not None:
        items = [u for u in items if u.get("consignment_listing_id") == cl_f]
    items = sorted_records(items)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_unit(u) for u in page], limit, offset, total)


@app.route("/units/<unit_id>/reserve", methods=["POST"])
def reserve_unit(unit_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    body = get_body()
    # existence: unit (path), then customer (body FK), left-to-right
    unit = get_unit(unit_id)
    customer_id = as_str(require(body, "customer_id"), "customer_id")
    expected_version = as_int(require(body, "expected_inventory_unit_version"), "expected_inventory_unit_version")
    get_customer(customer_id)
    # state before OCC (priority 5 before 6)
    if unit["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Unit is not AVAILABLE")
    if expected_version != unit["version"]:
        raise err("ERR_STALE_VERSION", "expected_inventory_unit_version does not match")
    unit["status"] = "RESERVED"
    unit["reserved_for_customer_id"] = customer_id
    M.touch(unit)
    return success(M.ser_unit(unit), status=200)


@app.route("/units/<unit_id>/release", methods=["POST"])
def release_unit(unit_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    unit = get_unit(unit_id)
    if unit["status"] != "RESERVED":
        raise err("ERR_INVALID_STATE", "Unit is not RESERVED")
    unit["status"] = "AVAILABLE"
    unit["reserved_for_customer_id"] = None
    M.touch(unit)
    return success(M.ser_unit(unit), status=200)


# ===========================================================================
# RentalAgreement
# ===========================================================================

@app.route("/rental-agreements", methods=["POST"])
def create_agreement():
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    body = get_body()
    customer_id = as_str(require(body, "customer_id"), "customer_id")
    inventory_unit_id = as_str(require(body, "inventory_unit_id"), "inventory_unit_id")
    plan = as_enum(require(body, "plan"), "plan", PLANS)
    equity_rate_pct = frac(opt(body, "equity_rate_pct", 0.50), "equity_rate_pct", 0.0, 1.0)
    equity_cap_pct = frac(opt(body, "equity_cap_pct", 1.0), "equity_cap_pct", 0.0, 1.0, lo_inclusive=False)

    # existence left-to-right: customer FK, then unit FK
    get_customer(customer_id)
    unit = get_unit(inventory_unit_id)

    # business-referential: unit reserved for this customer
    if unit["status"] != "RESERVED" or unit.get("reserved_for_customer_id") != customer_id:
        raise err("ERR_RESERVATION_MISMATCH", "Unit is not reserved for this customer")

    rec = M.new_common({
        "customer_id": customer_id,
        "inventory_unit_id": inventory_unit_id,
        "plan": plan,
        "monthly_rate_cents": unit["monthly_rent_cents"],
        "purchase_price_cents": unit["list_price_cents"],
        "equity_rate_pct": equity_rate_pct,
        "equity_cap_pct": equity_cap_pct,
        "missed_streak": 0,
        "status": "ACTIVE",
    })
    db.agreements[rec["id"]] = rec
    M.recompute_agreement(rec)

    # cascade: unit RESERVED -> ON_RENT
    unit["status"] = "ON_RENT"
    M.touch(unit)

    return success(M.ser_agreement(rec), status=201)


@app.route("/rental-agreements/<agreement_id>", methods=["GET"])
def get_agreement_route(agreement_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    rec = get_agreement(agreement_id)
    enforce_customer_owns(identity, rec["customer_id"])
    M.recompute_agreement(rec)
    return success(M.ser_agreement(rec), status=200)


@app.route("/rental-agreements", methods=["GET"])
def list_agreements():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.agreements.values())
    customer_f = request.args.get("customer_id")
    unit_f = request.args.get("inventory_unit_id")
    if customer_f is not None:
        items = [a for a in items if a["customer_id"] == customer_f]
    if unit_f is not None:
        items = [a for a in items if a["inventory_unit_id"] == unit_f]
    if identity.is_customer:
        items = [a for a in items if a["customer_id"] == identity.user_id]
    items = sorted_records(items)
    for a in items:
        M.recompute_agreement(a)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_agreement(a) for a in page], limit, offset, total)


@app.route("/rental-agreements/<agreement_id>/payments", methods=["POST"])
def post_rent_payment(agreement_id):
    identity = authenticate()
    require_role(identity, {"Customer", "SalesAssociate"})
    agr = get_agreement(agreement_id)
    enforce_customer_owns(identity, agr["customer_id"])
    body = get_body()
    billing_cycle_index = as_int(require(body, "billing_cycle_index"), "billing_cycle_index")

    if agr["status"] not in ("ACTIVE", "DEFAULTED"):
        raise err("ERR_INVALID_STATE", "Agreement is not in a payable state")

    payment = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "kind": "RENT",
        "amount_cents": agr["monthly_rate_cents"],
        "billing_cycle_index": billing_cycle_index,
        "status": "POSTED",
        "created_at": db.stamp(),
        "_seq": db.next_seq(),
    }
    db.payment_records[payment["id"]] = payment

    # recompute missed_streak: count consecutive trailing cycles still unpaid.
    _recompute_missed_streak(agr)
    M.recompute_agreement(agr)

    # DEFAULTED -> ACTIVE recovery if streak now below threshold
    if agr["status"] == "DEFAULTED" and agr["missed_streak"] < calc.DEFAULT_THRESHOLD:
        agr["status"] = "ACTIVE"

    M.touch(agr)
    return success(M.ser_payment(payment), status=201)


@app.route("/rental-agreements/<agreement_id>/payments", methods=["GET"])
def list_rent_payments(agreement_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    agr = get_agreement(agreement_id)
    enforce_customer_owns(identity, agr["customer_id"])
    limit, offset = parse_pagination()
    items = M.agreement_payments(agreement_id)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_payment(p) for p in page], limit, offset, total)


def _recompute_missed_streak(agr):
    """Recompute missed_streak = consecutive missed billing cycles since the last
    POSTED rent payment, processing cycles by billing_cycle_index asc, ties by
    created_at asc.

    The highest billing cycle reached is max(advanced cycle, paid cycles). A
    cycle counts as paid if a POSTED RENT record exists for it. The streak is the
    number of trailing cycles (from the max downward) with no POSTED rent.
    """
    paid_cycles = set()
    for p in db.payment_records.values():
        if (p["agreement_id"] == agr["id"] and p["kind"] == "RENT"
                and p["status"] == "POSTED" and p["billing_cycle_index"] is not None):
            paid_cycles.add(p["billing_cycle_index"])

    highest = agr.get("_highest_cycle", 0)
    if paid_cycles:
        highest = max(highest, max(paid_cycles))
    agr["_highest_cycle"] = highest

    streak = 0
    cycle = highest
    while cycle >= 1:
        if cycle in paid_cycles:
            break
        streak += 1
        cycle -= 1
    agr["missed_streak"] = streak


@app.route("/rental-agreements/<agreement_id>/advance-cycle", methods=["POST"])
def advance_cycle(agreement_id):
    identity = authenticate()
    require_role(identity, {"StoreManager", "SalesAssociate"})
    agr = get_agreement(agreement_id)
    body = get_body()
    cycle = as_int(require(body, "billing_cycle_index"), "billing_cycle_index")

    if agr["status"] not in ("ACTIVE", "DEFAULTED"):
        raise err("ERR_INVALID_STATE", "Agreement is not in an advanceable state")

    agr["_highest_cycle"] = max(agr.get("_highest_cycle", 0), cycle)

    # does a POSTED RENT exist for this cycle?
    paid = any(
        p["agreement_id"] == agreement_id and p["kind"] == "RENT"
        and p["status"] == "POSTED" and p["billing_cycle_index"] == cycle
        for p in db.payment_records.values()
    )
    if not paid:
        late = {
            "id": db.new_id(),
            "agreement_id": agreement_id,
            "kind": "LATE_FEE",
            "amount_cents": calc.LATE_FEE_CENTS,
            "billing_cycle_index": None,
            "status": "POSTED",
            "created_at": db.stamp(),
            "_seq": db.next_seq(),
        }
        db.payment_records[late["id"]] = late

    _recompute_missed_streak(agr)
    M.recompute_agreement(agr)

    if agr["status"] == "ACTIVE" and agr["missed_streak"] >= calc.DEFAULT_THRESHOLD:
        agr["status"] = "DEFAULTED"

    M.touch(agr)
    return success(M.ser_agreement(agr), status=200)


@app.route("/rental-agreements/<agreement_id>/buyout", methods=["POST"])
def buyout_agreement(agreement_id):
    identity = authenticate()
    require_role(identity, {"Customer", "SalesAssociate"})
    agr = get_agreement(agreement_id)
    enforce_customer_owns(identity, agr["customer_id"])
    body = get_body()
    amount_cents = as_int(require(body, "amount_cents"), "amount_cents")
    expected_version = as_int(require(body, "expected_agreement_version"), "expected_agreement_version")

    # state (priority 5)
    if agr["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Agreement is not ACTIVE")
    # OCC (priority 6)
    if expected_version != agr["version"]:
        raise err("ERR_STALE_VERSION", "expected_agreement_version does not match")
    # plan eligibility (priority 7)
    if agr["plan"] != "RENT_TO_OWN":
        raise err("ERR_PLAN_NOT_RENT_TO_OWN", "Buyout requires a RENT_TO_OWN plan")
    # exact payoff (priority 12)
    M.recompute_agreement(agr)
    if amount_cents != agr["payoff_quote_cents"]:
        raise err("ERR_PAYOFF_MISMATCH", "amount_cents must equal payoff_quote_cents")

    payment = {
        "id": db.new_id(),
        "agreement_id": agreement_id,
        "kind": "BUYOUT",
        "amount_cents": agr["payoff_quote_cents"],
        "billing_cycle_index": None,
        "status": "POSTED",
        "created_at": db.stamp(),
        "_seq": db.next_seq(),
    }
    db.payment_records[payment["id"]] = payment

    agr["status"] = "BOUGHT_OUT"
    # cascade: unit ON_RENT -> SOLD
    unit = db.units.get(agr["inventory_unit_id"])
    if unit is not None:
        unit["status"] = "SOLD"
        M.touch(unit)
    M.recompute_agreement(agr)
    M.touch(agr)
    return success(M.ser_agreement(agr), status=200)


@app.route("/rental-agreements/<agreement_id>/return", methods=["POST"])
def return_agreement(agreement_id):
    identity = authenticate()
    require_role(identity, {"Customer", "SalesAssociate"})
    agr = get_agreement(agreement_id)
    enforce_customer_owns(identity, agr["customer_id"])

    if agr["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Agreement is not ACTIVE")
    M.recompute_agreement(agr)
    if agr["late_fee_balance_cents"] > 0:
        raise err("ERR_OUTSTANDING_LATE_FEES", "Outstanding late fees block return")

    agr["status"] = "RETURNED"
    unit = db.units.get(agr["inventory_unit_id"])
    if unit is not None:
        unit["status"] = "AVAILABLE"
        unit["reserved_for_customer_id"] = None
        M.touch(unit)
    M.touch(agr)
    return success(M.ser_agreement(agr), status=200)


@app.route("/rental-agreements/<agreement_id>/repossess", methods=["POST"])
def repossess_agreement(agreement_id):
    identity = authenticate()
    require_role(identity, {"StoreManager"})
    agr = get_agreement(agreement_id)
    if agr["status"] != "DEFAULTED":
        raise err("ERR_INVALID_STATE", "Agreement is not DEFAULTED")

    # write off outstanding late-fee balance: move POSTED LATE_FEE -> WAIVED
    for p in db.payment_records.values():
        if (p["agreement_id"] == agreement_id and p["kind"] == "LATE_FEE"
                and p["status"] == "POSTED"):
            p["status"] = "WAIVED"

    agr["status"] = "REPOSSESSED"
    unit = db.units.get(agr["inventory_unit_id"])
    if unit is not None:
        unit["status"] = "IN_REPAIR"
        M.touch(unit)
    M.recompute_agreement(agr)
    M.touch(agr)
    return success(M.ser_agreement(agr), status=200)


# ===========================================================================
# LayawayPlan
# ===========================================================================

@app.route("/layaway-plans", methods=["POST"])
def create_layaway():
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    body = get_body()
    customer_id = as_str(require(body, "customer_id"), "customer_id")
    inventory_unit_id = as_str(require(body, "inventory_unit_id"), "inventory_unit_id")
    deposit_cents = int_min(require(body, "deposit_cents"), "deposit_cents", 0)
    restock_fee_pct = frac(opt(body, "restock_fee_pct", 0.10), "restock_fee_pct", 0.0, 1.0)

    get_customer(customer_id)
    unit = get_unit(inventory_unit_id)

    if unit["status"] != "RESERVED" or unit.get("reserved_for_customer_id") != customer_id:
        raise err("ERR_RESERVATION_MISMATCH", "Unit is not reserved for this customer")

    rec = M.new_common({
        "customer_id": customer_id,
        "inventory_unit_id": inventory_unit_id,
        "total_price_cents": unit["list_price_cents"],
        "deposit_cents": deposit_cents,
        "restock_fee_pct": restock_fee_pct,
        "status": "OPEN",
    })
    db.layaway_plans[rec["id"]] = rec
    M.recompute_layaway(rec)

    unit["status"] = "ON_LAYAWAY"
    M.touch(unit)
    return success(M.ser_layaway(rec), status=201)


@app.route("/layaway-plans/<plan_id>", methods=["GET"])
def get_layaway_route(plan_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    rec = get_layaway(plan_id)
    enforce_customer_owns(identity, rec["customer_id"])
    M.recompute_layaway(rec)
    return success(M.ser_layaway(rec), status=200)


@app.route("/layaway-plans", methods=["GET"])
def list_layaways():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.layaway_plans.values())
    customer_f = request.args.get("customer_id")
    unit_f = request.args.get("inventory_unit_id")
    if customer_f is not None:
        items = [p for p in items if p["customer_id"] == customer_f]
    if unit_f is not None:
        items = [p for p in items if p["inventory_unit_id"] == unit_f]
    if identity.is_customer:
        items = [p for p in items if p["customer_id"] == identity.user_id]
    items = sorted_records(items)
    for p in items:
        M.recompute_layaway(p)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_layaway(p) for p in page], limit, offset, total)


@app.route("/layaway-plans/<plan_id>/payments", methods=["POST"])
def post_layaway_payment(plan_id):
    identity = authenticate()
    require_role(identity, {"Customer", "SalesAssociate"})
    plan = get_layaway(plan_id)
    enforce_customer_owns(identity, plan["customer_id"])
    body = get_body()
    amount_cents = as_int(require(body, "amount_cents"), "amount_cents")
    if amount_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be > 0")
    if plan["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Layaway plan is not OPEN")

    payment = {
        "id": db.new_id(),
        "layaway_plan_id": plan_id,
        "amount_cents": amount_cents,
        "created_at": db.stamp(),
        "_seq": db.next_seq(),
    }
    db.layaway_payments[payment["id"]] = payment
    M.recompute_layaway(plan)
    M.touch(plan)
    return success(M.ser_layaway_payment(payment), status=201)


@app.route("/layaway-plans/<plan_id>/payments", methods=["GET"])
def list_layaway_payments(plan_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    plan = get_layaway(plan_id)
    enforce_customer_owns(identity, plan["customer_id"])
    limit, offset = parse_pagination()
    items = [p for p in db.layaway_payments.values() if p["layaway_plan_id"] == plan_id]
    items = sorted_records(items)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_layaway_payment(p) for p in page], limit, offset, total)


@app.route("/layaway-plans/<plan_id>/complete", methods=["POST"])
def complete_layaway(plan_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    plan = get_layaway(plan_id)
    if plan["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Layaway plan is not OPEN")
    M.recompute_layaway(plan)
    if plan["remaining_cents"] != 0:
        raise err("ERR_LAYAWAY_NOT_PAID", "Layaway is not fully paid")

    plan["status"] = "COMPLETED"
    unit = db.units.get(plan["inventory_unit_id"])
    if unit is not None:
        unit["status"] = "SOLD"
        M.touch(unit)
    M.touch(plan)
    return success(M.ser_layaway(plan), status=200)


@app.route("/layaway-plans/<plan_id>/cancel", methods=["POST"])
def cancel_layaway(plan_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    plan = get_layaway(plan_id)
    if plan["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Layaway plan is not OPEN")
    M.recompute_layaway(plan)

    refund = calc.layaway_cancel_refund(
        plan["total_price_cents"], plan["restock_fee_pct"], plan["paid_cents"]
    )
    plan["status"] = "CANCELLED"
    unit = db.units.get(plan["inventory_unit_id"])
    if unit is not None:
        unit["status"] = "AVAILABLE"
        unit["reserved_for_customer_id"] = None
        M.touch(unit)
    if refund > 0:
        M.credit_customer(plan["customer_id"], refund)
    M.touch(plan)
    return success(M.ser_layaway(plan), status=200)


# ===========================================================================
# RepairTicket
# ===========================================================================

@app.route("/repair-tickets", methods=["POST"])
def create_repair():
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    body = get_body()
    customer_id = as_str(require(body, "customer_id"), "customer_id")
    labor_hours = as_number(require(body, "labor_hours"), "labor_hours")
    if labor_hours < 0:
        raise err("ERR_INVALID_REQUEST", "labor_hours must be >= 0")
    labor_rate_cents = int_min(require(body, "labor_rate_cents"), "labor_rate_cents", 0)
    inventory_unit_id = opt(body, "inventory_unit_id", None)
    parts_cost_cents = int_min(opt(body, "parts_cost_cents", 0), "parts_cost_cents", 0)
    rush = as_bool(opt(body, "rush", False), "rush")

    get_customer(customer_id)
    unit = None
    if inventory_unit_id is not None:
        unit = get_unit(inventory_unit_id)

    quoted = calc.repair_invoice(labor_hours, labor_rate_cents, parts_cost_cents, rush)

    rec = M.new_common({
        "customer_id": customer_id,
        "inventory_unit_id": inventory_unit_id,
        "assigned_luthier_id": None,
        "labor_hours": labor_hours,
        "labor_rate_cents": labor_rate_cents,
        "parts_cost_cents": parts_cost_cents,
        "rush": rush,
        "quoted_total_cents": quoted,
        "status": "INTAKE",
    })
    db.repair_tickets[rec["id"]] = rec

    # cascade: store-owned AVAILABLE unit -> IN_REPAIR
    if unit is not None and unit["status"] == "AVAILABLE":
        unit["status"] = "IN_REPAIR"
        M.touch(unit)

    return success(M.ser_repair(rec), status=201)


@app.route("/repair-tickets/<ticket_id>", methods=["GET"])
def get_repair_route(ticket_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Luthier", "Customer"})
    rec = get_repair(ticket_id)
    enforce_customer_owns(identity, rec["customer_id"])
    return success(M.ser_repair(rec), status=200)


@app.route("/repair-tickets", methods=["GET"])
def list_repairs():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Luthier", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.repair_tickets.values())
    customer_f = request.args.get("customer_id")
    unit_f = request.args.get("inventory_unit_id")
    status_f = request.args.get("status")
    if customer_f is not None:
        items = [t for t in items if t["customer_id"] == customer_f]
    if unit_f is not None:
        items = [t for t in items if t.get("inventory_unit_id") == unit_f]
    if status_f is not None:
        items = [t for t in items if t["status"] == status_f]
    if identity.is_customer:
        items = [t for t in items if t["customer_id"] == identity.user_id]
    items = sorted_records(items)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_repair(t) for t in page], limit, offset, total)


def _release_repair_unit(ticket):
    if ticket.get("inventory_unit_id") is None:
        return
    unit = db.units.get(ticket["inventory_unit_id"])
    if unit is not None and unit["status"] == "IN_REPAIR":
        unit["status"] = "AVAILABLE"
        M.touch(unit)


@app.route("/repair-tickets/<ticket_id>/claim", methods=["POST"])
def claim_repair(ticket_id):
    identity = authenticate()
    require_role(identity, {"Luthier"})
    rec = get_repair(ticket_id)
    if rec["status"] != "INTAKE":
        raise err("ERR_INVALID_STATE", "Ticket is not in INTAKE")
    rec["status"] = "IN_PROGRESS"
    rec["assigned_luthier_id"] = identity.user_id
    M.touch(rec)
    return success(M.ser_repair(rec), status=200)


@app.route("/repair-tickets/<ticket_id>/await-parts", methods=["POST"])
def await_parts(ticket_id):
    identity = authenticate()
    require_role(identity, {"Luthier"})
    rec = get_repair(ticket_id)
    if rec["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Ticket is not IN_PROGRESS")
    if identity.user_id != rec["assigned_luthier_id"]:
        raise err("ERR_TICKET_NOT_ASSIGNED", "Ticket is assigned to another luthier")
    rec["status"] = "AWAITING_PARTS"
    M.touch(rec)
    return success(M.ser_repair(rec), status=200)


@app.route("/repair-tickets/<ticket_id>/resume", methods=["POST"])
def resume_repair(ticket_id):
    identity = authenticate()
    require_role(identity, {"Luthier"})
    rec = get_repair(ticket_id)
    if rec["status"] != "AWAITING_PARTS":
        raise err("ERR_INVALID_STATE", "Ticket is not AWAITING_PARTS")
    if identity.user_id != rec["assigned_luthier_id"]:
        raise err("ERR_TICKET_NOT_ASSIGNED", "Ticket is assigned to another luthier")
    rec["status"] = "IN_PROGRESS"
    M.touch(rec)
    return success(M.ser_repair(rec), status=200)


@app.route("/repair-tickets/<ticket_id>/ready", methods=["POST"])
def ready_repair(ticket_id):
    identity = authenticate()
    require_role(identity, {"Luthier"})
    rec = get_repair(ticket_id)
    if rec["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Ticket is not IN_PROGRESS")
    if identity.user_id != rec["assigned_luthier_id"]:
        raise err("ERR_TICKET_NOT_ASSIGNED", "Ticket is assigned to another luthier")
    rec["status"] = "READY"
    # quoted_total_cents frozen (already computed; no recompute after READY)
    rec["_frozen"] = True
    M.touch(rec)
    return success(M.ser_repair(rec), status=200)


@app.route("/repair-tickets/<ticket_id>/close", methods=["POST"])
def close_repair(ticket_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    rec = get_repair(ticket_id)
    if rec["status"] != "READY":
        raise err("ERR_INVALID_STATE", "Ticket is not READY")
    rec["status"] = "CLOSED"
    _release_repair_unit(rec)
    M.touch(rec)
    return success(M.ser_repair(rec), status=200)


@app.route("/repair-tickets/<ticket_id>/cancel", methods=["POST"])
def cancel_repair(ticket_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    rec = get_repair(ticket_id)
    if rec["status"] not in ("INTAKE", "IN_PROGRESS", "AWAITING_PARTS"):
        raise err("ERR_INVALID_STATE", "Ticket cannot be cancelled from its current state")
    rec["status"] = "CANCELLED"
    _release_repair_unit(rec)
    M.touch(rec)
    return success(M.ser_repair(rec), status=200)


# ===========================================================================
# ConsignmentListing
# ===========================================================================

@app.route("/consignment-listings", methods=["POST"])
def create_consignment():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager"})
    body = get_body()
    consignor_id = as_str(require(body, "consignor_id"), "consignor_id")
    model_name = as_str(require(body, "model_name"), "model_name")
    ask_price_cents = as_int(require(body, "ask_price_cents"), "ask_price_cents")
    if ask_price_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "ask_price_cents must be > 0")
    commission_pct = frac(opt(body, "commission_pct", 0.20), "commission_pct", 0.0, 1.0)

    get_customer(consignor_id)

    rec = M.new_common({
        "consignor_id": consignor_id,
        "model_name": model_name,
        "ask_price_cents": ask_price_cents,
        "commission_pct": commission_pct,
        "consignor_payout_cents": 0,
        "status": "LISTED",
    })
    db.consignment_listings[rec["id"]] = rec

    # mint a CONSIGNED backing unit linked one-to-one
    unit = M.mint_unit(
        model_name=model_name,
        category="OTHER",
        condition="USED",
        serial_number="CONSIGN-" + rec["id"],
        acquisition_cost_cents=0,
        list_price_cents=ask_price_cents,
        monthly_rent_cents=0,
        status="CONSIGNED",
        source_kind="CONSIGNMENT",
        consignment_listing_id=rec["id"],
    )
    rec["_unit_id"] = unit["id"]
    return success(M.ser_consignment(rec), status=201)


@app.route("/consignment-listings/<listing_id>", methods=["GET"])
def get_consignment_route(listing_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    rec = get_consignment(listing_id)
    enforce_customer_owns(identity, rec["consignor_id"])
    return success(M.ser_consignment(rec), status=200)


@app.route("/consignment-listings", methods=["GET"])
def list_consignments():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.consignment_listings.values())
    consignor_f = request.args.get("consignor_id")
    status_f = request.args.get("status")
    if consignor_f is not None:
        items = [c for c in items if c["consignor_id"] == consignor_f]
    if status_f is not None:
        items = [c for c in items if c["status"] == status_f]
    if identity.is_customer:
        items = [c for c in items if c["consignor_id"] == identity.user_id]
    items = sorted_records(items)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_consignment(c) for c in page], limit, offset, total)


def _consignment_unit(listing):
    uid = listing.get("_unit_id")
    if uid is None:
        # fallback: find by FK
        for u in db.units.values():
            if u.get("consignment_listing_id") == listing["id"]:
                return u
        return None
    return db.units.get(uid)


@app.route("/consignment-listings/<listing_id>/sell", methods=["POST"])
def sell_consignment(listing_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    rec = get_consignment(listing_id)
    unit = _consignment_unit(rec)
    if rec["status"] != "LISTED" or unit is None or unit["status"] != "CONSIGNED":
        raise err("ERR_INVALID_STATE", "Listing is not in a sellable state")

    payout = calc.consignment_settlement(rec["ask_price_cents"], rec["commission_pct"])
    rec["status"] = "SOLD"
    rec["consignor_payout_cents"] = payout
    unit["status"] = "SOLD"
    M.touch(unit)
    M.credit_customer(rec["consignor_id"], payout)
    M.touch(rec)
    return success(M.ser_consignment(rec), status=200)


@app.route("/consignment-listings/<listing_id>/withdraw", methods=["POST"])
def withdraw_consignment(listing_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager"})
    rec = get_consignment(listing_id)
    if rec["status"] != "LISTED":
        raise err("ERR_INVALID_STATE", "Listing is not LISTED")
    rec["status"] = "WITHDRAWN"
    unit = _consignment_unit(rec)
    if unit is not None:
        unit["status"] = "RETIRED"
        M.touch(unit)
    M.touch(rec)
    return success(M.ser_consignment(rec), status=200)


# ===========================================================================
# TradeIn
# ===========================================================================

@app.route("/trade-ins", methods=["POST"])
def create_tradein():
    identity = authenticate()
    require_role(identity, {"StoreManager"})
    body = get_body()
    customer_id = as_str(require(body, "customer_id"), "customer_id")
    model_name = as_str(require(body, "model_name"), "model_name")
    condition = as_enum(require(body, "condition"), "condition", CONDITIONS)
    appraised_value_cents = int_min(require(body, "appraised_value_cents"), "appraised_value_cents", 0)

    get_customer(customer_id)
    offer = calc.tradein_offer(appraised_value_cents, condition)

    rec = M.new_common({
        "customer_id": customer_id,
        "model_name": model_name,
        "condition": condition,
        "appraised_value_cents": appraised_value_cents,
        "offer_cents": offer,
        "resulting_unit_id": None,
        "status": "OFFERED",
    })
    db.trade_ins[rec["id"]] = rec
    return success(M.ser_tradein(rec), status=201)


@app.route("/trade-ins/<trade_in_id>", methods=["GET"])
def get_tradein_route(trade_in_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    rec = get_tradein(trade_in_id)
    enforce_customer_owns(identity, rec["customer_id"])
    return success(M.ser_tradein(rec), status=200)


@app.route("/trade-ins", methods=["GET"])
def list_tradeins():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.trade_ins.values())
    customer_f = request.args.get("customer_id")
    unit_f = request.args.get("resulting_unit_id")
    status_f = request.args.get("status")
    if customer_f is not None:
        items = [t for t in items if t["customer_id"] == customer_f]
    if unit_f is not None:
        items = [t for t in items if t.get("resulting_unit_id") == unit_f]
    if status_f is not None:
        items = [t for t in items if t["status"] == status_f]
    if identity.is_customer:
        items = [t for t in items if t["customer_id"] == identity.user_id]
    items = sorted_records(items)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_tradein(t) for t in page], limit, offset, total)


@app.route("/trade-ins/<trade_in_id>/accept", methods=["POST"])
def accept_tradein(trade_in_id):
    identity = authenticate()
    require_role(identity, {"StoreManager"})
    rec = get_tradein(trade_in_id)
    if rec["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Trade-in is not OFFERED")

    unit = M.mint_unit(
        model_name=rec["model_name"],
        category="OTHER",
        condition=rec["condition"],
        serial_number="TRADEIN-" + rec["id"],
        acquisition_cost_cents=rec["offer_cents"],
        list_price_cents=0,
        monthly_rent_cents=0,
        status="AVAILABLE",
        source_kind="TRADE_IN",
    )
    rec["status"] = "ACCEPTED"
    rec["resulting_unit_id"] = unit["id"]
    M.credit_customer(rec["customer_id"], rec["offer_cents"])
    M.touch(rec)
    return success(M.ser_tradein(rec), status=200)


@app.route("/trade-ins/<trade_in_id>/decline", methods=["POST"])
def decline_tradein(trade_in_id):
    identity = authenticate()
    require_role(identity, {"Customer", "StoreManager"})
    rec = get_tradein(trade_in_id)
    enforce_customer_owns(identity, rec["customer_id"])
    if rec["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Trade-in is not OFFERED")
    rec["status"] = "DECLINED"
    M.touch(rec)
    return success(M.ser_tradein(rec), status=200)


# ===========================================================================
# FinancingApplication
# ===========================================================================

@app.route("/financing-applications", methods=["POST"])
def create_financing():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "Customer"})
    body = get_body()
    customer_id = as_str(require(body, "customer_id"), "customer_id")
    principal_cents = as_int(require(body, "principal_cents"), "principal_cents")
    if principal_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "principal_cents must be > 0")
    term_months = as_int(require(body, "term_months"), "term_months")
    if term_months not in TERM_MONTHS:
        raise err("ERR_INVALID_REQUEST", "term_months must be one of 6, 12, 24, 36")
    special_order_id = opt(body, "special_order_id", None)

    # ownership for customer-submitted applications
    enforce_customer_owns(identity, customer_id)
    get_customer(customer_id)
    if special_order_id is not None:
        get_special_order(special_order_id)

    rec = M.new_common({
        "customer_id": customer_id,
        "special_order_id": special_order_id,
        "principal_cents": principal_cents,
        "term_months": term_months,
        "apr_pct": None,
        "monthly_payment_cents": None,
        "status": "SUBMITTED",
    })
    db.financing_applications[rec["id"]] = rec
    return success(M.ser_financing(rec), status=201)


@app.route("/financing-applications/<application_id>", methods=["GET"])
def get_financing_route(application_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    rec = get_financing(application_id)
    enforce_customer_owns(identity, rec["customer_id"])
    return success(M.ser_financing(rec), status=200)


@app.route("/financing-applications", methods=["GET"])
def list_financing():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.financing_applications.values())
    customer_f = request.args.get("customer_id")
    order_f = request.args.get("special_order_id")
    status_f = request.args.get("status")
    if customer_f is not None:
        items = [a for a in items if a["customer_id"] == customer_f]
    if order_f is not None:
        items = [a for a in items if a.get("special_order_id") == order_f]
    if status_f is not None:
        items = [a for a in items if a["status"] == status_f]
    if identity.is_customer:
        items = [a for a in items if a["customer_id"] == identity.user_id]
    items = sorted_records(items)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_financing(a) for a in page], limit, offset, total)


@app.route("/financing-applications/<application_id>/approve", methods=["POST"])
def approve_financing(application_id):
    identity = authenticate()
    require_role(identity, {"StoreManager"})
    rec = get_financing(application_id)
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Application is not SUBMITTED")
    cust = db.customers[rec["customer_id"]]
    if cust["credit_score"] < calc.MIN_FINANCE_SCORE:
        raise err("ERR_CREDIT_TOO_LOW", "Credit score below financing minimum")

    apr, monthly = calc.financing_terms(rec["principal_cents"], rec["term_months"], cust["credit_score"])
    rec["status"] = "APPROVED"
    rec["apr_pct"] = apr
    rec["monthly_payment_cents"] = monthly

    # cascade: linked special order QUOTED/DEPOSITED -> ORDERED
    if rec.get("special_order_id") is not None:
        order = db.special_orders.get(rec["special_order_id"])
        if order is not None and order["status"] in ("QUOTED", "DEPOSITED"):
            order["status"] = "ORDERED"
            M.touch(order)
    M.touch(rec)
    return success(M.ser_financing(rec), status=200)


@app.route("/financing-applications/<application_id>/deny", methods=["POST"])
def deny_financing(application_id):
    identity = authenticate()
    require_role(identity, {"StoreManager"})
    rec = get_financing(application_id)
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Application is not SUBMITTED")
    rec["status"] = "DENIED"
    M.touch(rec)
    return success(M.ser_financing(rec), status=200)


@app.route("/financing-applications/<application_id>/cancel", methods=["POST"])
def cancel_financing(application_id):
    identity = authenticate()
    require_role(identity, {"Customer"})
    rec = get_financing(application_id)
    enforce_customer_owns(identity, rec["customer_id"])
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Application is not SUBMITTED")
    rec["status"] = "CANCELLED"
    M.touch(rec)
    return success(M.ser_financing(rec), status=200)


# ===========================================================================
# SpecialOrder
# ===========================================================================

@app.route("/special-orders", methods=["POST"])
def create_special_order():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "Customer"})
    body = get_body()
    customer_id = as_str(require(body, "customer_id"), "customer_id")
    model_name = as_str(require(body, "model_name"), "model_name")
    quoted_price_cents = as_int(require(body, "quoted_price_cents"), "quoted_price_cents")
    if quoted_price_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "quoted_price_cents must be > 0")
    deposit_pct = frac(opt(body, "deposit_pct", 0.25), "deposit_pct", 0.0, 1.0)

    enforce_customer_owns(identity, customer_id)
    get_customer(customer_id)

    required_deposit = calc.special_order_deposit(quoted_price_cents, deposit_pct)
    rec = M.new_common({
        "customer_id": customer_id,
        "model_name": model_name,
        "quoted_price_cents": quoted_price_cents,
        "deposit_pct": deposit_pct,
        "required_deposit_cents": required_deposit,
        "deposit_paid_cents": 0,
        "fulfilled_unit_id": None,
        "status": "QUOTED",
    })
    db.special_orders[rec["id"]] = rec
    return success(M.ser_special_order(rec), status=201)


@app.route("/special-orders/<order_id>", methods=["GET"])
def get_special_order_route(order_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    rec = get_special_order(order_id)
    enforce_customer_owns(identity, rec["customer_id"])
    return success(M.ser_special_order(rec), status=200)


@app.route("/special-orders", methods=["GET"])
def list_special_orders():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.special_orders.values())
    customer_f = request.args.get("customer_id")
    unit_f = request.args.get("fulfilled_unit_id")
    status_f = request.args.get("status")
    if customer_f is not None:
        items = [o for o in items if o["customer_id"] == customer_f]
    if unit_f is not None:
        items = [o for o in items if o.get("fulfilled_unit_id") == unit_f]
    if status_f is not None:
        items = [o for o in items if o["status"] == status_f]
    if identity.is_customer:
        items = [o for o in items if o["customer_id"] == identity.user_id]
    items = sorted_records(items)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_special_order(o) for o in page], limit, offset, total)


@app.route("/special-orders/<order_id>/pay-deposit", methods=["POST"])
def pay_deposit(order_id):
    identity = authenticate()
    require_role(identity, {"Customer", "SalesAssociate"})
    rec = get_special_order(order_id)
    enforce_customer_owns(identity, rec["customer_id"])
    body = get_body()
    amount_cents = as_int(require(body, "amount_cents"), "amount_cents")
    if rec["status"] != "QUOTED":
        raise err("ERR_INVALID_STATE", "Order is not QUOTED")
    if amount_cents < rec["required_deposit_cents"]:
        raise err("ERR_DEPOSIT_INSUFFICIENT", "Deposit is below the required amount")
    rec["status"] = "DEPOSITED"
    rec["deposit_paid_cents"] = amount_cents
    M.touch(rec)
    return success(M.ser_special_order(rec), status=200)


@app.route("/special-orders/<order_id>/place", methods=["POST"])
def place_special_order(order_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    rec = get_special_order(order_id)
    if rec["status"] != "DEPOSITED":
        raise err("ERR_INVALID_STATE", "Order is not DEPOSITED")
    rec["status"] = "ORDERED"
    M.touch(rec)
    return success(M.ser_special_order(rec), status=200)


@app.route("/special-orders/<order_id>/receive", methods=["POST"])
def receive_special_order(order_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    rec = get_special_order(order_id)
    body = get_body()
    serial_number = as_str(require(body, "serial_number"), "serial_number")
    category = as_enum(require(body, "category"), "category", CATEGORIES)
    if rec["status"] != "ORDERED":
        raise err("ERR_INVALID_STATE", "Order is not ORDERED")

    unit = M.mint_unit(
        model_name=rec["model_name"],
        category=category,
        condition="NEW",
        serial_number=serial_number,
        acquisition_cost_cents=0,
        list_price_cents=rec["quoted_price_cents"],
        monthly_rent_cents=0,
        status="RESERVED",
        source_kind="STORE_PURCHASE",
        reserved_for_customer_id=rec["customer_id"],
    )
    rec["status"] = "ARRIVED"
    rec["fulfilled_unit_id"] = unit["id"]
    M.touch(rec)
    return success(M.ser_special_order(rec), status=200)


@app.route("/special-orders/<order_id>/fulfill", methods=["POST"])
def fulfill_special_order(order_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate"})
    rec = get_special_order(order_id)
    if rec["status"] != "ARRIVED":
        raise err("ERR_INVALID_STATE", "Order is not ARRIVED")
    rec["status"] = "FULFILLED"
    unit = db.units.get(rec.get("fulfilled_unit_id"))
    if unit is not None:
        unit["status"] = "SOLD"
        M.touch(unit)
    M.touch(rec)
    return success(M.ser_special_order(rec), status=200)


@app.route("/special-orders/<order_id>/cancel", methods=["POST"])
def cancel_special_order(order_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "Customer"})
    rec = get_special_order(order_id)
    enforce_customer_owns(identity, rec["customer_id"])
    if rec["status"] not in ("QUOTED", "DEPOSITED", "ORDERED"):
        raise err("ERR_INVALID_STATE", "Order cannot be cancelled from its current state")
    refund = rec["deposit_paid_cents"]
    rec["status"] = "CANCELLED"
    if refund > 0:
        M.credit_customer(rec["customer_id"], refund)
    M.touch(rec)
    return success(M.ser_special_order(rec), status=200)


# ===========================================================================
# LessonEnrollment
# ===========================================================================

def _bundle_active(rental_agreement_id):
    if rental_agreement_id is None:
        return False
    agr = db.agreements.get(rental_agreement_id)
    return agr is not None and agr["status"] == "ACTIVE"


@app.route("/lesson-enrollments", methods=["POST"])
def create_lesson():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "Customer"})
    body = get_body()
    student_id = as_str(require(body, "student_id"), "student_id")
    instrument_family = as_enum(require(body, "instrument_family"), "instrument_family", CATEGORIES)
    sessions_per_month = as_int(require(body, "sessions_per_month"), "sessions_per_month")
    if sessions_per_month <= 0:
        raise err("ERR_INVALID_REQUEST", "sessions_per_month must be > 0")
    base_rate_cents = int_min(require(body, "base_rate_cents"), "base_rate_cents", 0)
    rental_agreement_id = opt(body, "rental_agreement_id", None)

    enforce_customer_owns(identity, student_id)
    get_customer(student_id)
    if rental_agreement_id is not None:
        get_agreement(rental_agreement_id)

    has_bundle = _bundle_active(rental_agreement_id)
    tuition = calc.lesson_tuition(base_rate_cents, sessions_per_month, has_bundle)

    rec = M.new_common({
        "student_id": student_id,
        "rental_agreement_id": rental_agreement_id,
        "instrument_family": instrument_family,
        "sessions_per_month": sessions_per_month,
        "base_rate_cents": base_rate_cents,
        "monthly_tuition_cents": tuition,
        "status": "ACTIVE",
    })
    db.lesson_enrollments[rec["id"]] = rec
    return success(M.ser_lesson(rec), status=201)


@app.route("/lesson-enrollments/<enrollment_id>", methods=["GET"])
def get_lesson_route(enrollment_id):
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    rec = get_lesson(enrollment_id)
    enforce_customer_owns(identity, rec["student_id"])
    return success(M.ser_lesson(rec), status=200)


@app.route("/lesson-enrollments", methods=["GET"])
def list_lessons():
    identity = authenticate()
    require_role(identity, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.lesson_enrollments.values())
    student_f = request.args.get("student_id")
    agr_f = request.args.get("rental_agreement_id")
    status_f = request.args.get("status")
    if student_f is not None:
        items = [e for e in items if e["student_id"] == student_f]
    if agr_f is not None:
        items = [e for e in items if e.get("rental_agreement_id") == agr_f]
    if status_f is not None:
        items = [e for e in items if e["status"] == status_f]
    if identity.is_customer:
        items = [e for e in items if e["student_id"] == identity.user_id]
    items = sorted_records(items)
    page, total = paginate(items, limit, offset)
    return list_success([M.ser_lesson(e) for e in page], limit, offset, total)


@app.route("/lesson-enrollments/<enrollment_id>/pause", methods=["POST"])
def pause_lesson(enrollment_id):
    identity = authenticate()
    require_role(identity, {"Customer", "SalesAssociate"})
    rec = get_lesson(enrollment_id)
    enforce_customer_owns(identity, rec["student_id"])
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment is not ACTIVE")
    rec["status"] = "PAUSED"
    M.touch(rec)
    return success(M.ser_lesson(rec), status=200)


@app.route("/lesson-enrollments/<enrollment_id>/resume", methods=["POST"])
def resume_lesson(enrollment_id):
    identity = authenticate()
    require_role(identity, {"Customer", "SalesAssociate"})
    rec = get_lesson(enrollment_id)
    enforce_customer_owns(identity, rec["student_id"])
    if rec["status"] != "PAUSED":
        raise err("ERR_INVALID_STATE", "Enrollment is not PAUSED")
    rec["status"] = "ACTIVE"
    has_bundle = _bundle_active(rec.get("rental_agreement_id"))
    rec["monthly_tuition_cents"] = calc.lesson_tuition(
        rec["base_rate_cents"], rec["sessions_per_month"], has_bundle
    )
    M.touch(rec)
    return success(M.ser_lesson(rec), status=200)


@app.route("/lesson-enrollments/<enrollment_id>/end", methods=["POST"])
def end_lesson(enrollment_id):
    identity = authenticate()
    require_role(identity, {"Customer", "SalesAssociate"})
    rec = get_lesson(enrollment_id)
    enforce_customer_owns(identity, rec["student_id"])
    if rec["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Enrollment cannot be ended from its current state")
    rec["status"] = "ENDED"
    M.touch(rec)
    return success(M.ser_lesson(rec), status=200)


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
