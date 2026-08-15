"""Fabrication order lifecycle endpoints."""
from decimal import Decimal
from flask import Blueprint, request

import db
from db import store, new_id, wall_now, touch
from errors import ApiError
from response import ok, created, paginate
from middleware import get_context, require_roles
from validation import parse_body, require_path_entity
from services.audit import audit
from services.pricing import recompute_committed
from services.nesting import simulate_nest, apply_nest, release_nest
from services.routing import (
    assign_machines, recompute_order_due, planned_minutes_for, IN_HOUSE,
)
from services.capacity import booked_minutes, can_absorb
from services.credits import apply_scrap_credit

bp = Blueprint("orders", __name__)

ORDER_READ_ROLES = ["ShopManager", "Estimator", "ProductionPlanner", "MachineOperator", "CustomerRep"]
PLANNER = ["ProductionPlanner"]


def _order_or_404(order_id):
    return require_path_entity(store.orders, order_id)


def _own_or_404(order, uid, role):
    if role == "CustomerRep" and order["customer_id"] != uid:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")


@bp.get("/fab/orders")
def list_orders():
    uid, role, _ = get_context()
    require_roles(ORDER_READ_ROLES)
    rows = list(store.orders.values())
    if role == "CustomerRep":
        rows = [o for o in rows if o["customer_id"] == uid]
    for f in ("customer_id", "status", "payment_status", "quote_id"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/fab/orders/<order_id>")
def get_order(order_id):
    uid, role, _ = get_context()
    require_roles(ORDER_READ_ROLES)
    o = _order_or_404(order_id)
    _own_or_404(o, uid, role)
    return ok(o)


@bp.post("/fab/orders/<order_id>/renest")
def renest(order_id):
    uid, role, _ = get_context()
    require_roles(PLANNER)
    o = _order_or_404(order_id)
    if o["status"] not in ("NESTING", "NESTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Renest requires the order to be NESTING or NESTED")

    lines = sorted(
        [ln for ln in store.quote_lines.values() if ln["quote_id"] == o["quote_id"]],
        key=lambda l: (l["created_at"], l["_seq"]),
    )
    # Virtual pool: currently AVAILABLE stock plus this order's consumed sheets;
    # this order's generated remnants are being scrapped and are not re-selectable.
    own_sheets = [ns for ns in store.nest_sheets.values() if ns["order_id"] == o["id"]]
    own_sheet_ids = {ns["sheet_stock_id"] for ns in own_sheets}
    own_remnant_ids = {ns["remnant_stock_id"] for ns in own_sheets if ns["remnant_stock_id"]}
    pool = []
    for s in store.sheet_stock.values():
        if s["id"] in own_remnant_ids:
            continue
        if s["status"] == "AVAILABLE" or s["id"] in own_sheet_ids:
            pool.append(s)
    nest_plan, nest_err = None, None
    try:
        nest_plan = simulate_nest(lines, pool)
    except ApiError as e:
        nest_err = e
    sheets_used = len(nest_plan) if nest_plan is not None else 0
    steps = sorted(
        [st for st in store.routing_steps.values() if st["order_id"] == o["id"]],
        key=lambda s: s["seq"],
    )
    stations = [st["station"] for st in steps]
    machine_ids, cap_err = assign_machines(stations, lines, sheets_used, exclude_order_id=o["id"])
    if cap_err is not None:
        raise cap_err
    if nest_err is not None:
        raise nest_err

    release_nest(o)
    apply_nest(o, nest_plan)
    recompute_committed(o, lines)
    audit("FabricationOrder", o["id"], "ORDER_RENESTED", role, uid,
          {"after": {"status": o["status"], "total_plate_area_cm2": o["total_plate_area_cm2"]}})
    for st in steps:
        if st["station"] in IN_HOUSE:
            st["planned_minutes"] = planned_minutes_for(st["station"], lines, sheets_used)
            st["machine_id"] = machine_ids[st["station"]]
        touch(st)
    recompute_order_due(o)
    touch(o)
    return ok(o)


@bp.post("/fab/orders/<order_id>/release")
def release_order(order_id):
    uid, role, _ = get_context()
    require_roles(PLANNER)
    o = _order_or_404(order_id)
    if o["status"] != "NESTED":
        raise ApiError("ERR_ORDER_NOT_RELEASEABLE", 409, "Release requires the order to be NESTED")
    steps = sorted(
        [st for st in store.routing_steps.values() if st["order_id"] == o["id"]],
        key=lambda s: s["seq"],
    )
    for st in steps:
        if st["station"] in IN_HOUSE:
            m = store.machines.get(st["machine_id"])
            if m is None or m["status"] != "ACTIVE":
                raise ApiError("ERR_MACHINE_DOWN", 409, "An assigned machine is DOWN")
    o["status"] = "IN_PRODUCTION"
    touch(o)
    if steps:
        steps[0]["status"] = "IN_PROGRESS"
        touch(steps[0])
    audit("FabricationOrder", o["id"], "ORDER_RELEASED", role, uid,
          {"before": {"status": "NESTED"}, "after": {"status": "IN_PRODUCTION"}})
    return ok(o)


@bp.post("/fab/orders/<order_id>/receive-outside")
def receive_outside(order_id):
    uid, role, _ = get_context()
    require_roles(PLANNER)
    o = _order_or_404(order_id)
    if o["status"] != "AWAITING_OUTSIDE":
        raise ApiError("ERR_ORDER_NOT_AWAITING_OUTSIDE", 409,
                       "Receive-outside requires the order to be AWAITING_OUTSIDE")
    steps = sorted(
        [st for st in store.routing_steps.values() if st["order_id"] == o["id"]],
        key=lambda s: s["seq"],
    )
    out_step = next(st for st in steps if st["station"] == "OUTSIDE_VENDOR")
    if db.LOGICAL_CLOCK < out_step["_due_dt"]:
        raise ApiError("ERR_VENDOR_LEAD_TIME_NOT_ELAPSED", 409,
                       "Vendor lead time has not elapsed on the logical clock")
    out_step["status"] = "COMPLETED"
    touch(out_step)
    next_step = next((st for st in steps if st["status"] == "PENDING"), None)
    if next_step is not None:
        next_step["status"] = "IN_PROGRESS"
        touch(next_step)
        o["status"] = "FINISHING"
    else:
        o["status"] = "INSPECTION"
    touch(o)
    recompute_order_due(o)
    audit("FabricationOrder", o["id"], "ORDER_RECEIVED_OUTSIDE", role, uid,
          {"before": {"status": "AWAITING_OUTSIDE"}, "after": {"status": o["status"]}})
    if o["status"] == "INSPECTION":
        audit("FabricationOrder", o["id"], "ORDER_READY_FOR_INSPECTION", "system", "system",
              {"after": {"status": "INSPECTION"}})
    return ok(o)


@bp.post("/fab/orders/<order_id>/hold")
def hold_order(order_id):
    uid, role, _ = get_context()
    require_roles(PLANNER)
    body = parse_body({"hold_reason": ("enum", True, ["CAPACITY", "VENDOR_DELAY"])},
                    allow_empty=False)
    o = _order_or_404(order_id)
    if o["status"] not in ("IN_PRODUCTION", "AWAITING_OUTSIDE", "FINISHING"):
        raise ApiError("ERR_ORDER_NOT_HOLDABLE", 409,
                       "Hold requires IN_PRODUCTION, AWAITING_OUTSIDE, or FINISHING")
    prev = o["status"]
    o["status"] = "ON_HOLD"
    o["hold_reason"] = body["hold_reason"]
    touch(o)
    audit("FabricationOrder", o["id"], "ORDER_HELD", role, uid,
          {"before": {"status": prev}, "after": {"status": "ON_HOLD", "hold_reason": body["hold_reason"]}})
    return ok(o)


@bp.post("/fab/orders/<order_id>/resume")
def resume_order(order_id):
    uid, role, _ = get_context()
    require_roles(PLANNER)
    o = _order_or_404(order_id)
    if o["status"] != "ON_HOLD":
        raise ApiError("ERR_ORDER_NOT_ON_HOLD", 409, "Resume requires the order to be ON_HOLD")
    # resume-target resolution: status recorded in the last ORDER_HELD audit event
    target = None
    for ev in store.audit_events:
        if ev["entity_type"] == "FabricationOrder" and ev["entity_id"] == o["id"] \
                and ev["event_type"] == "ORDER_HELD":
            target = ev["detail"].get("before", {}).get("status")
    if target not in ("IN_PRODUCTION", "AWAITING_OUTSIDE", "FINISHING"):
        target = "IN_PRODUCTION"
    # capacity re-validation with machine reassignment per selector
    steps = [st for st in store.routing_steps.values()
             if st["order_id"] == o["id"] and st["status"] in ("PENDING", "IN_PROGRESS")
             and st["station"] in IN_HOUSE]
    steps.sort(key=lambda s: s["seq"])
    original = {st["id"]: st["machine_id"] for st in steps}
    for st in steps:
        st["machine_id"] = None
    try:
        for st in steps:
            candidates = [m for m in store.machines.values()
                          if m["station"] == st["station"] and m["status"] == "ACTIVE"]
            candidates.sort(key=lambda m: (booked_minutes(m["id"]), m["created_at"], m["_seq"]))
            chosen = None
            for m in candidates:
                if can_absorb(m, booked_minutes(m["id"]), st["planned_minutes"]):
                    chosen = m
                    break
            if chosen is None:
                raise ApiError("ERR_NO_MACHINE_CAPACITY", 409,
                               "No ACTIVE machine can absorb the step within the utilization cap")
            st["machine_id"] = chosen["id"]
    except ApiError:
        for st in steps:
            st["machine_id"] = original[st["id"]]
        raise
    o["status"] = target
    o["hold_reason"] = None
    touch(o)
    for st in steps:
        touch(st)
    audit("FabricationOrder", o["id"], "ORDER_RESUMED", role, uid,
          {"before": {"status": "ON_HOLD"}, "after": {"status": target}})
    return ok(o)


@bp.post("/fab/orders/<order_id>/cancel")
def cancel_order(order_id):
    uid, role, _ = get_context()
    require_roles(PLANNER)
    o = _order_or_404(order_id)
    if o["status"] not in ("NESTING", "NESTED"):
        raise ApiError("ERR_ORDER_NOT_CANCELLABLE", 409, "Cancel requires NESTING or NESTED")
    release_nest(o)
    o["committed_subtotal_cents"] = 0
    o["committed_total_cents"] = 0
    o["status"] = "CANCELLED"
    touch(o)
    audit("FabricationOrder", o["id"], "ORDER_CANCELLED", role, uid,
          {"after": {"status": "CANCELLED"}})
    return ok(o)


@bp.post("/fab/orders/<order_id>/inspection-reports")
def submit_inspection(order_id):
    uid, role, _ = get_context()
    require_roles(["QCInspector"])
    body = parse_body({
        "flatness_deviation_mm": ("number", True, None),
        "measured_diagonal_mm": ("integer", True, None),
        "dimensional_pass": ("boolean", True, None),
        "result": ("enum", False, ["PASS", "FAIL"]),
    }, allow_empty=False)
    o = _order_or_404(order_id)
    if o["status"] != "INSPECTION":
        raise ApiError("ERR_ORDER_NOT_IN_INSPECTION", 409,
                       "Inspection reports require the order to be INSPECTION")
    steps = sorted(
        [st for st in store.routing_steps.values() if st["order_id"] == o["id"]],
        key=lambda s: s["seq"],
    )
    completed = [st for st in steps if st["status"] == "COMPLETED"]
    last_completed = completed[-1] if completed else None
    if last_completed is not None and last_completed.get("completing_operator_id") == uid:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "Inspector must differ from the operator who completed the last routing step")

    deviation = Decimal(str(body["flatness_deviation_mm"]))
    diagonal = body["measured_diagonal_mm"]
    if diagonal <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "measured_diagonal_mm must be positive")
    # exact ratio comparison without rounding: deviation / diagonal <= 0.0015
    passes_flatness = deviation * 2000 <= Decimal(3) * Decimal(diagonal)
    result = "PASS" if (passes_flatness and body["dimensional_pass"]) else "FAIL"
    if body.get("result") == "PASS" and result == "FAIL":
        raise ApiError("ERR_FLATNESS_EXCEEDED", 422,
                       "Computed FAIL cannot be overridden by a declared PASS")

    if result == "FAIL":
        # rework loop: implicated COMPLETED steps reset to PENDING, minutes re-booked
        # on the same machine; capacity re-validated before any mutation.
        reset_steps = [st for st in steps if st["status"] == "COMPLETED"]
        for st in reset_steps:
            if st["station"] in IN_HOUSE and st["machine_id"]:
                m = store.machines.get(st["machine_id"])
                others = booked_minutes(st["machine_id"])
                if m is not None and not can_absorb(m, others, st["planned_minutes"]):
                    raise ApiError("ERR_NO_MACHINE_CAPACITY", 409,
                                   "Rework re-booking exceeds machine capacity")
        for st in reset_steps:
            st["status"] = "PENDING"
            touch(st)
        o["status"] = "IN_PRODUCTION"
        touch(o)
        pending = sorted([st for st in store.routing_steps.values()
                          if st["order_id"] == o["id"] and st["status"] == "PENDING"],
                         key=lambda s: s["seq"])
        if pending:
            pending[0]["status"] = "IN_PROGRESS"
            touch(pending[0])
    report = {
        "id": new_id(),
        "order_id": o["id"],
        "inspector_id": uid,
        "flatness_deviation_mm": body["flatness_deviation_mm"],
        "measured_diagonal_mm": body["measured_diagonal_mm"],
        "dimensional_pass": body["dimensional_pass"],
        "result": result,
        "created_at": wall_now(),
    }
    store.inspection_reports[report["id"]] = report
    if result == "PASS":
        o["status"] = "COMPLETED"
        o["completed_at"] = db.iso_logical(db.LOGICAL_CLOCK)
        touch(o)
        audit("FabricationOrder", o["id"], "ORDER_COMPLETED", role, uid,
              {"before": {"status": "INSPECTION"}, "after": {"status": "COMPLETED"}})
    else:
        audit("FabricationOrder", o["id"], "INSPECTION_FAIL_REWORK", role, uid,
              {"before": {"status": "INSPECTION"}, "after": {"status": "IN_PRODUCTION"}})
    return created(report)


@bp.get("/fab/orders/<order_id>/inspection-reports")
def list_inspection_reports(order_id):
    uid, role, _ = get_context()
    require_roles(["ShopManager", "ProductionPlanner", "QCInspector"])
    o = _order_or_404(order_id)
    rows = [r for r in store.inspection_reports.values() if r["order_id"] == o["id"]]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/fab/orders/<order_id>/payment")
def pay_order(order_id):
    uid, role, _ = get_context()
    require_roles(["CustomerRep"])
    body = parse_body({"scrap_credit_to_apply_cents": ("integer", False, None)})
    o = _order_or_404(order_id)
    if o["customer_id"] != uid:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    if o["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "Payment requires a COMPLETED order")
    if o["payment_status"] != "UNPAID":
        raise ApiError("ERR_ALREADY_PAID", 409, "Order is already paid")
    requested = body.get("scrap_credit_to_apply_cents", 0)
    if requested < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "scrap_credit_to_apply_cents must be >= 0")
    customer = store.customers[o["customer_id"]]
    if requested > customer["scrap_credit_balance_cents"]:
        raise ApiError("ERR_INSUFFICIENT_SCRAP_CREDIT", 402,
                       "Requested scrap credit exceeds the customer balance")
    applied = min(requested, customer["scrap_credit_balance_cents"], o["committed_total_cents"])
    if applied > 0:
        apply_scrap_credit(customer, applied)
    o["scrap_credit_applied_cents"] = applied
    o["payment_status"] = "PAID"
    o["paid_at"] = db.iso_logical(db.LOGICAL_CLOCK)
    touch(o)
    audit("FabricationOrder", o["id"], "ORDER_PAID", role, uid,
          {"before": {"payment_status": "UNPAID"},
           "after": {"payment_status": "PAID", "scrap_credit_applied_cents": applied}})
    return ok(o)


@bp.get("/fab/orders/<order_id>/nest-sheets")
def list_order_nest_sheets(order_id):
    uid, role, _ = get_context()
    require_roles(["ShopManager", "Estimator", "ProductionPlanner"])
    o = _order_or_404(order_id)
    rows = [ns for ns in store.nest_sheets.values() if ns["order_id"] == o["id"]]
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.get("/fab/orders/<order_id>/routing-steps")
def list_order_routing_steps(order_id):
    uid, role, _ = get_context()
    require_roles(["ShopManager", "ProductionPlanner", "MachineOperator", "QCInspector"])
    o = _order_or_404(order_id)
    rows = [st for st in store.routing_steps.values() if st["order_id"] == o["id"]]
    return ok(paginate(rows), rtype="array", pagination=paginate)
