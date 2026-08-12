"""ProductionOrder endpoints plus order-scoped creation of allocations,
batches, shortfalls, and filling runs."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

from core import (body, check_enum, check_int, err, get_required, list_page,
                  new_entity, require_roles, success, touch)
from services import (D, cancel_order_cascade, compute_changeover_minutes,
                      compute_quote, fulfillable_units, line_window_overlaps,
                      must_get, lot_unexpired, num, previous_run_on_line,
                      reserve_on_lot, serialize_allocation, serialize_batch,
                      serialize_order, serialize_run, serialize_shortfall)
from store import db, parse_dt

bp = Blueprint("orders", __name__)

ORDER_READ_ROLES = ("CustomerRep", "ProductionPlanner", "QAManager",
                    "PlantDirector", "FormulationChemist")


def check_order_confidentiality(order):
    if g.user_role == "CustomerRep" and order["customer_id"] != g.user_id:
        err("ERR_CONFIDENTIALITY_VIOLATION", 403,
            "CustomerRep may only access their own orders")


def recompute_order_financials(order):
    formula = db.formulas.get(order["formula_id"])
    customer = db.customers.get(order["customer_id"])
    if formula is not None and customer is not None:
        order["quote_total_cents"] = compute_quote(formula, customer,
                                                   order["requested_units"])


# ---------------------------------------------------------------------------
# Order CRUD and lifecycle
# ---------------------------------------------------------------------------


@bp.post("/cosmfg/production-orders")
@require_roles("CustomerRep")
def create_order():
    b = body()
    customer = db.customers.get(g.user_id)
    if customer is None:
        err("ERR_NOT_FOUND", 404, f"Customer not found: {g.user_id}")
    formula = must_get(db.formulas, get_required(b, "formula_id"), "Formula")
    if formula["customer_id"] != customer["id"]:
        err("ERR_FORMULA_CUSTOMER_MISMATCH", 422,
            "Order's formula belongs to a different customer")
    if formula["status"] != "ACTIVE":
        err("ERR_FORMULA_NOT_ACTIVE", 409, "Referenced formula is not ACTIVE")
    units = check_int(get_required(b, "requested_units"), "requested_units", minimum=1)
    if units < customer["minimum_run_units"]:
        err("ERR_BELOW_MINIMUM_RUN", 422,
            "requested_units is below the customer's minimum_run_units")
    o = new_entity()
    o.update({
        "customer_id": customer["id"],
        "formula_id": formula["id"],
        "formula_version_seq": None,
        "requested_units": units,
        "forfeited_units": 0,
        "filled_units": 0,
        "status": "DRAFT",
        "hold_return_status": None,
        "quote_total_cents": compute_quote(formula, customer, units),
    })
    db.orders[o["id"]] = o
    return success(serialize_order(o), status=201)


@bp.get("/cosmfg/production-orders/<oid>")
@require_roles(*ORDER_READ_ROLES)
def get_order(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    check_order_confidentiality(o)
    return success(serialize_order(o))


@bp.get("/cosmfg/production-orders")
@require_roles("CustomerRep", "ProductionPlanner", "QAManager", "PlantDirector")
def list_orders():
    items = list(db.orders.values())
    if g.user_role == "CustomerRep":
        items = [o for o in items if o["customer_id"] == g.user_id]
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    formula_id = request.args.get("formula_id")
    if formula_id is not None:
        items = [o for o in items if o["formula_id"] == formula_id]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_page(items, serialize_order)


@bp.patch("/cosmfg/production-orders/<oid>")
@require_roles("CustomerRep")
def patch_order(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    check_order_confidentiality(o)
    b = body()
    expected = get_required(b, "expected_production_order_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        err("ERR_VALIDATION", 400, "expected_production_order_version must be an integer")
    if expected != o["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_production_order_version does not match the order's current version")
    if o["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409,
            "requested_units may only be updated while the order is DRAFT")
    units = check_int(get_required(b, "requested_units"), "requested_units", minimum=1)
    customer = db.customers.get(o["customer_id"])
    if customer is not None and units < customer["minimum_run_units"]:
        err("ERR_BELOW_MINIMUM_RUN", 422,
            "requested_units is below the customer's minimum_run_units")
    o["requested_units"] = units
    recompute_order_financials(o)
    touch(o)
    return success(serialize_order(o))


@bp.post("/cosmfg/production-orders/<oid>/confirm")
@require_roles("CustomerRep")
def confirm_order(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    check_order_confidentiality(o)
    if o["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Only a DRAFT order may be confirmed")
    formula = db.formulas.get(o["formula_id"])
    if formula is None or formula["status"] != "ACTIVE":
        err("ERR_FORMULA_NOT_ACTIVE", 409, "Referenced formula is not ACTIVE")
    customer = db.customers.get(o["customer_id"])
    if customer is not None and o["requested_units"] < customer["minimum_run_units"]:
        err("ERR_BELOW_MINIMUM_RUN", 422,
            "requested_units is below the customer's minimum_run_units")
    recompute_order_financials(o)
    if (customer is not None
            and customer["outstanding_balance_cents"] + o["quote_total_cents"]
            > customer["credit_limit_cents"]):
        err("ERR_CREDIT_LIMIT_EXCEEDED", 402,
            "Confirm would push the customer's outstanding balance above credit_limit_cents")
    o["formula_version_seq"] = formula["version_seq"]
    o["status"] = "CONFIRMED"
    touch(o)
    if customer is not None:
        customer["outstanding_balance_cents"] = (
            customer["outstanding_balance_cents"] + o["quote_total_cents"])
        touch(customer)
    return success(serialize_order(o))


@bp.post("/cosmfg/production-orders/<oid>/cancel")
@require_roles("CustomerRep", "ProductionPlanner")
def cancel_order(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    check_order_confidentiality(o)
    if o["status"] in ("COMPLETED", "CANCELLED"):
        err("ERR_INVALID_STATE", 409, "Terminal orders reject every further transition")
    cancel_order_cascade(o)
    return success(serialize_order(o))


@bp.post("/cosmfg/production-orders/<oid>/resume")
@require_roles("ProductionPlanner")
def resume_order(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    if o["status"] != "ON_HOLD":
        err("ERR_INVALID_STATE", 409, "Only an ON_HOLD order may be resumed")
    formula = db.formulas.get(o["formula_id"])
    if formula is None or formula["status"] not in ("IN_REVIEW", "APPROVED", "ACTIVE"):
        err("ERR_FORMULA_NOT_ACTIVE", 409,
            "Referenced formula must be IN_REVIEW, APPROVED, or ACTIVE to resume")
    o["status"] = o["hold_return_status"]
    o["hold_return_status"] = None
    touch(o)
    return success(serialize_order(o))


# ---------------------------------------------------------------------------
# Order-scoped list endpoints
# ---------------------------------------------------------------------------


def _filter_status(items):
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return items


@bp.get("/cosmfg/production-orders/<oid>/batches")
@require_roles("ProductionPlanner", "QAManager", "PlantDirector")
def list_order_batches(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    items = _filter_status([b for b in db.batches.values()
                            if b["production_order_id"] == o["id"]])
    return list_page(items, serialize_batch)


@bp.get("/cosmfg/production-orders/<oid>/allocations")
@require_roles("ProductionPlanner", "QAManager", "PlantDirector", "CustomerRep")
def list_order_allocations(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    check_order_confidentiality(o)
    items = _filter_status([a for a in db.allocations.values()
                            if a["production_order_id"] == o["id"]])
    return list_page(items, serialize_allocation)


@bp.get("/cosmfg/production-orders/<oid>/shortfalls")
@require_roles("ProductionPlanner", "CustomerRep", "PlantDirector")
def list_order_shortfalls(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    check_order_confidentiality(o)
    items = _filter_status([s for s in db.shortfalls.values()
                            if s["production_order_id"] == o["id"]])
    return list_page(items, serialize_shortfall)


@bp.get("/cosmfg/production-orders/<oid>/filling-runs")
@require_roles("ProductionPlanner", "QAManager", "PlantDirector")
def list_order_runs(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    items = _filter_status([r for r in db.runs.values()
                            if r["production_order_id"] == o["id"]])
    return list_page(items, serialize_run)


# ---------------------------------------------------------------------------
# Allocations (order-scoped creation)
# ---------------------------------------------------------------------------


@bp.post("/cosmfg/production-orders/<oid>/allocations")
@require_roles("ProductionPlanner")
def create_allocations(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    if o["status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        err("ERR_INVALID_STATE", 409,
            "Reservations require the order in CONFIRMED or IN_PRODUCTION")
    b = body()
    items = b.get("items")
    if not isinstance(items, list) or not items:
        err("ERR_VALIDATION", 400, "items must be a non-empty array")
    prepared = []
    for item in items:
        if not isinstance(item, dict):
            err("ERR_VALIDATION", 400, "Each allocation item must be an object")
        lot = must_get(db.lots, get_required(item, "lot_id"), "ComponentLot")
        batch_id = item.get("batch_id")
        if batch_id is not None:
            batch = must_get(db.batches, batch_id, "Batch")
            if batch["production_order_id"] != o["id"]:
                err("ERR_BATCH_ORDER_MISMATCH", 422,
                    "batch_id must reference a batch of the same production order")
        # Priority 8: lot expiry against the logical clock
        if not lot_unexpired(lot):
            err("ERR_LOT_EXPIRED", 422,
                "Allocated lot has expires_at <= current logical clock")
        comp = must_get(db.components, lot["component_id"], "Component")
        # Priority 13: customer-supplied lots serve only the owning customer
        if (comp["supply_mode"] == "CUSTOMER_SUPPLIED"
                and comp.get("customer_id") != o["customer_id"]):
            err("ERR_COMPONENT_OWNERSHIP_MISMATCH", 422,
                "CUSTOMER_SUPPLIED lots may only be allocated to orders of the owning customer")
        # Priority 14: MINOR_VARIANT lots must be WAIVED
        if lot["sensorial_profile"] == "MINOR_VARIANT" and lot["variant_waiver"] != "WAIVED":
            err("ERR_VARIANT_WAIVER_REQUIRED", 422,
                "MINOR_VARIANT lots require variant_waiver == WAIVED before allocation")
        # Priority 25: availability
        qty = item.get("quantity")
        if qty is not None and (isinstance(qty, bool) or not isinstance(qty, (int, float))):
            err("ERR_VALIDATION", 400, "quantity must be a number")
        if lot["status"] != "AVAILABLE" or (qty is not None and D(qty) > D(lot["quantity_available"])):
            err("ERR_LOT_INSUFFICIENT_QUANTITY", 422,
                "Allocation quantity exceeds lot.quantity_available or lot is not AVAILABLE")
        # Priority 29: request shape
        if qty is None:
            err("ERR_VALIDATION", 400, "Missing required field: quantity")
        if D(qty) <= 0:
            err("ERR_VALIDATION", 400, "quantity must be > 0")
        prepared.append((lot, qty, batch_id))
    created = []
    for lot, qty, batch_id in prepared:
        a = new_entity()
        a.update({
            "production_order_id": o["id"],
            "batch_id": batch_id,
            "lot_id": lot["id"],
            "quantity": qty,
            "status": "RESERVED",
        })
        db.allocations[a["id"]] = a
        reserve_on_lot(lot, qty)
        created.append(a)
    return success([serialize_allocation(a) for a in created], status=201,
                   response_type="array")


# ---------------------------------------------------------------------------
# Batch creation (order-scoped)
# ---------------------------------------------------------------------------


@bp.post("/cosmfg/production-orders/<oid>/batches")
@require_roles("ProductionPlanner")
def create_batch(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    if o["status"] not in ("CONFIRMED", "IN_PRODUCTION"):
        err("ERR_INVALID_STATE", 409,
            "Batches may only be planned for CONFIRMED or IN_PRODUCTION orders")
    b = body()
    size = b.get("batch_size_kg")
    if size is None:
        err("ERR_VALIDATION", 400, "Missing required field: batch_size_kg")
    if isinstance(size, bool) or not isinstance(size, (int, float)) or D(size) <= 0:
        err("ERR_VALIDATION", 400, "batch_size_kg must be a number > 0")
    batch = new_entity()
    batch.update({
        "production_order_id": o["id"],
        "batch_size_kg": size,
        "scale_up_factor": float(D(size) / D(50)),
        "scale_up_approved": False,
        "status": "PLANNED",
        "failed_check_count": 0,
        "round_viscosity_result": "NONE",
        "round_ph_result": "NONE",
        "last_ipc_recorded_by_user_id": None,
        "batch_charge_cents": None,
        "batch_charge_standard_cents": None,
    })
    db.batches[batch["id"]] = batch
    return success(serialize_batch(batch), status=201)


# ---------------------------------------------------------------------------
# Shortfall declaration (order-scoped)
# ---------------------------------------------------------------------------


@bp.post("/cosmfg/production-orders/<oid>/shortfalls")
@require_roles("ProductionPlanner")
def create_shortfall(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    if o["status"] in ("COMPLETED", "CANCELLED"):
        err("ERR_INVALID_STATE", 409,
            "Shortfalls may not be declared against a terminal order")
    b = body()
    comp = must_get(db.components, get_required(b, "component_id"), "Component")
    if comp["supply_mode"] != "CUSTOMER_SUPPLIED" or comp.get("customer_id") != o["customer_id"]:
        err("ERR_COMPONENT_OWNERSHIP_MISMATCH", 422,
            "Shortfall component must be CUSTOMER_SUPPLIED and owned by the order's customer")
    required = b.get("required_quantity")
    if required is None:
        err("ERR_VALIDATION", 400, "Missing required field: required_quantity")
    if isinstance(required, bool) or not isinstance(required, (int, float)):
        err("ERR_VALIDATION", 400, "required_quantity must be a number")
    allocatable = Decimal("0")
    for lot in db.lots.values():
        if lot["component_id"] != comp["id"]:
            continue
        if lot["status"] != "AVAILABLE" or not lot_unexpired(lot):
            continue
        allocatable += D(lot["quantity_available"])
    shortfall = D(required) - allocatable
    if shortfall <= 0:
        err("ERR_NO_SHORTFALL", 422, "Declared shortfall_quantity computes to <= 0")
    s = new_entity()
    s.update({
        "production_order_id": o["id"],
        "component_id": comp["id"],
        "required_quantity": required,
        "allocatable_quantity": float(allocatable),
        "shortfall_quantity": float(shortfall),
        "status": "OPEN",
        "committed_by_date": None,
        "resolution": None,
        "covered_quantity": 0,  # internal proration bookkeeping; not serialized
    })
    db.shortfalls[s["id"]] = s
    return success(serialize_shortfall(s), status=201)


# ---------------------------------------------------------------------------
# Filling-run scheduling (order-scoped)
# ---------------------------------------------------------------------------


@bp.post("/cosmfg/production-orders/<oid>/filling-runs")
@require_roles("ProductionPlanner")
def create_filling_run(oid):
    o = must_get(db.orders, oid, "ProductionOrder")
    b = body()
    line = must_get(db.lines, get_required(b, "line_id"), "FillingLine")
    batch = must_get(db.batches, get_required(b, "batch_id"), "Batch")
    # Fixed check order (PRD 3.8): batch-order match, occupancy, changeover,
    # planned-units cap.
    if batch["production_order_id"] != o["id"]:
        err("ERR_BATCH_ORDER_MISMATCH", 422,
            "FillingRun.batch_id references a batch of a different production order")
    start_raw = b.get("scheduled_start")
    end_raw = b.get("scheduled_end")
    start_dt = parse_dt(start_raw)
    end_dt = parse_dt(end_raw)
    if start_dt is None or end_dt is None:
        err("ERR_VALIDATION", 400,
            "scheduled_start and scheduled_end must be ISO-8601 datetimes")
    if end_dt <= start_dt:
        err("ERR_VALIDATION", 400, "scheduled_end must be after scheduled_start")
    if line_window_overlaps(line["id"], start_dt, end_dt):
        err("ERR_LINE_OCCUPIED", 409,
            "New run's window intersects an existing SCHEDULED/IN_PROGRESS run on the line")
    changeover = compute_changeover_minutes(o, line["id"], start_dt)
    prev = previous_run_on_line(line["id"], start_dt)
    if prev is not None and start_dt < prev["_end_dt"] + timedelta(minutes=changeover):
        err("ERR_CHANGEOVER_GAP_VIOLATION", 409,
            "Gap after the previous run is smaller than changeover_minutes_required")
    planned = b.get("planned_units")
    if planned is not None and (isinstance(planned, bool) or not isinstance(planned, int)):
        err("ERR_VALIDATION", 400, "planned_units must be an integer")
    formula = db.formulas.get(o["formula_id"])
    cap = 0
    if formula is not None and D(formula["bulk_mass_per_unit_kg"]) > 0:
        cap = int(D(batch["batch_size_kg"]) // D(formula["bulk_mass_per_unit_kg"]))
    if planned is not None and planned > cap:
        err("ERR_PLANNED_UNITS_EXCEED_BATCH", 422,
            "planned_units exceeds floor(batch_size_kg / bulk_mass_per_unit_kg)")
    if planned is None:
        err("ERR_VALIDATION", 400, "Missing required field: planned_units")
    if planned < 1:
        err("ERR_VALIDATION", 400, "planned_units must be >= 1")
    r = new_entity()
    r.update({
        "production_order_id": o["id"],
        "line_id": line["id"],
        "batch_id": batch["id"],
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "planned_units": planned,
        "filled_units": None,
        "rejected_units": 0,
        "changeover_minutes_required": changeover,
        "status": "SCHEDULED",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    db.runs[r["id"]] = r
    return success(serialize_run(r), status=201)
