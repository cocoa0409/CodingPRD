"""Work-order (span) execution endpoints."""
from flask import Blueprint, request

import constants as C
import envelope
import services
import store
import validate as V
from auth import ALL_ROLES, endpoint
from errors import ApiError

bp = Blueprint("workorders", __name__)


@bp.post("/vm/work-orders")
@endpoint(["ContractorPlanner"])
def create_work_order():
    data = V.body()
    plan = V.body_fk(data, "work_plan_id", store.work_plans, "ERR_WORK_PLAN_NOT_FOUND")
    if plan is None:
        V.require(data, "work_plan_id")
    span_miles = V.as_number(data, "span_miles", minimum=0, exclusive_min=True)
    billing_method = V.as_enum(data, "billing_method", C.BILLING_METHODS)
    planned_units = V.as_integer(data, "planned_unit_count", minimum=0)

    rec = store.new_record()
    rec.update({
        "work_plan_id": plan["id"],
        "parent_work_order_id": None,
        "storm_event_id": None,
        "span_miles": span_miles,
        "billing_method": billing_method,
        "planned_unit_count": planned_units,
        "clearance_radius_ft": None,
        "actual_units_completed": 0,
        "refusal_blocked_unit_count": 0,
        "execution_status": "PLANNED",
        "billing_status": "NOT_BILLABLE",
        "completed_at": None,
    })
    store.work_orders[rec["id"]] = rec
    services.recompute_plan(plan)
    return envelope.created(store.public(rec))


@bp.post("/vm/work-orders/<wid>/map")
@endpoint(["ContractorPlanner"])
def map_work_order(wid):
    work_order = V.find(store.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    data = V.body()
    clearance = V.as_number(data, "clearance_radius_ft", minimum=0)
    mapped_units = V.as_integer(data, "mapped_unit_count", required=False, minimum=0)

    services.require_state(work_order, "work_order", ["PLANNED"], field="execution_status")
    plan = services.plan_of_order(work_order)
    if plan is None or plan.get("status") not in ("DRAFT", "RELEASED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "the owning plan does not accept mapping")
    circuit = services.circuit_of_plan(plan)
    prescription = services.prescription_of_circuit(circuit)
    if prescription is not None and clearance < prescription.get("clearance_radius_ft"):
        raise ApiError("ERR_CLEARANCE_BELOW_PRESCRIPTION",
                       "clearance_radius_ft is below the resolved prescription")

    work_order["clearance_radius_ft"] = clearance
    if mapped_units is not None:
        work_order["planned_unit_count"] = mapped_units
    work_order["execution_status"] = "MAPPED"
    store.touch(work_order)
    services.recompute_plan(plan, bump=False)
    store.touch(plan)
    return envelope.ok(store.public(work_order))


@bp.post("/vm/work-orders/<wid>/release")
@endpoint(["ContractorPlanner"])
def release_work_order(wid):
    work_order = V.find(store.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    services.require_state(work_order, "work_order", ["MAPPED"], field="execution_status")
    plan = services.plan_of_order(work_order)
    if plan is None or plan.get("status") not in ("RELEASED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "the owning plan is not released")
    circuit = services.circuit_of_plan(plan)
    prescription = services.prescription_of_circuit(circuit)
    if prescription is None or prescription.get("status") != "ACTIVE":
        raise ApiError("ERR_PRESCRIPTION_NOT_ACTIVE",
                       "the circuit's resolved prescription is not ACTIVE")
    work_order["execution_status"] = "RELEASED"
    store.touch(work_order)
    return envelope.ok(store.public(work_order))


@bp.post("/vm/work-orders/<wid>/start")
@endpoint(["ContractorPlanner"])
def start_work_order(wid):
    work_order = V.find(store.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    services.require_state(work_order, "work_order", ["RELEASED"], field="execution_status")
    bookings = services.order_assignments(work_order["id"])
    if not any(a.get("status") == "SCHEDULED" for a in bookings):
        raise ApiError("ERR_INVALID_STATE", "the span has no SCHEDULED booking")
    work_order["execution_status"] = "IN_PROGRESS"
    store.touch(work_order)
    for assignment in bookings:
        if assignment.get("status") != "SCHEDULED":
            continue
        assignment["status"] = "ACTIVE"
        store.touch(assignment)
        crew = services.crew_of_assignment(assignment)
        if crew is not None and crew.get("status") != "ASSIGNED":
            crew["status"] = "ASSIGNED"
            store.touch(crew)
    plan = services.plan_of_order(work_order)
    services.plan_begin_execution(plan)
    services.recompute_plan(plan)
    return envelope.ok(store.public(work_order))


@bp.post("/vm/work-orders/<wid>/complete")
@endpoint(["ContractorPlanner"])
def complete_work_order(wid):
    work_order = V.find(store.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    services.require_state(work_order, "work_order", ["IN_PROGRESS"],
                           field="execution_status")
    for note in services.order_notifications(work_order["id"]):
        if note.get("status") in ("REFUSED", "ESCALATED"):
            raise ApiError("ERR_CUSTOMER_REFUSAL_BLOCKING",
                           "an unresolved customer refusal blocks completion")
    work_order["execution_status"] = "COMPLETED"
    work_order["completed_at"] = store.now_iso()
    services.derive_billing_status(work_order, bump=False)
    store.touch(work_order)
    services.release_order_assignments(work_order)
    plan = services.plan_of_order(work_order)
    services.recompute_plan(plan)
    services.plan_maybe_complete(plan)
    return envelope.ok(store.public(work_order))


@bp.post("/vm/work-orders/<wid>/cancel")
@endpoint(["ContractorPlanner"])
def cancel_work_order(wid):
    work_order = V.find(store.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    services.require_state(work_order, "work_order", ["PLANNED", "MAPPED", "RELEASED"],
                           field="execution_status")
    services.cancel_order(work_order)
    services.recompute_plan(services.plan_of_order(work_order))
    return envelope.ok(store.public(work_order))


@bp.get("/vm/work-orders/<wid>")
@endpoint(ALL_ROLES)
def get_work_order(wid):
    work_order = V.find(store.work_orders, wid, "ERR_WORK_ORDER_NOT_FOUND")
    return envelope.ok(store.public(work_order))


@bp.get("/vm/work-orders")
@endpoint(ALL_ROLES)
def list_work_orders():
    return envelope.list_response(list(store.work_orders.values()), {
        "work_plan_id": request.args.get("work_plan_id"),
        "parent_work_order_id": request.args.get("parent_work_order_id"),
        "storm_event_id": request.args.get("storm_event_id"),
        "execution_status": request.args.get("execution_status"),
        "billing_status": request.args.get("billing_status"),
    })
