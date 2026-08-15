from flask import Blueprint

from auth import authenticate, require_role
from db import store
from envelope import success_object, success_list
from errors import raise_err, ERR_PRODUCTION_ORDER_NOT_FOUND, \
    ERR_BOTTLE_SPEC_NOT_FOUND, ERR_MACHINE_LINE_NOT_FOUND, \
    ERR_INVALID_STATE, ERR_ALREADY_TERMINAL, ERR_STALE_VERSION, \
    ERR_SPEC_NOT_QUALIFIED, ERR_SCHEDULE_OVERLAP, ERR_LABELER_REQUIRED, \
    ERR_CREDIT_LIMIT_EXCEEDED, ERR_PLANNED_WEIGHT_OUT_OF_TOLERANCE, \
    ERR_NO_ACTIVE_SLOT, ERR_SPEC_REVISION_STALE, ERR_INSUFFICIENT_MATERIAL
from services import stamp_new, touch, ser_production_order, \
    ser_schedule_slot, sorted_rows, cancel_slots_for_order, create_slot, \
    maybe_advance_spec, schedule_conflict, credit_check, hold_order, \
    occupying_order_id, order_rollups, total_available, installed_mold_on_line
from util import new_id
from validate import get_body, check_fields, pagination_params, query_filter

bp = Blueprint("production_orders", __name__)

READ_ROLES = ["PlantAdmin", "ProcessEngineer", "QualityTechnician",
              "ProductionScheduler", "LogisticsCoordinator"]
SLOT_READ_ROLES = ["PlantAdmin", "ProcessEngineer", "ProductionScheduler"]
ORDER_STATUSES = {"DRAFT", "SCHEDULED", "RELEASED", "RUNNING", "HELD",
                  "COMPLETED", "CANCELLED"}
SLOT_STATUSES = {"CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
ORDER_TERMINAL = ("COMPLETED", "CANCELLED")


def get_order_or_404(order_id):
    order = store.production_orders.get(order_id)
    if order is None:
        raise_err(ERR_PRODUCTION_ORDER_NOT_FOUND,
                  "ProductionOrder id does not resolve")
    return order


def check_terminal(order):
    if order["status"] in ORDER_TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL,
                  "Order is in a terminal state")


def planned_weight_in_tolerance(spec, planned_weight_g):
    target = spec["target_weight_g"]
    band = target * spec["weight_tolerance_pct"] / 100
    return abs(planned_weight_g - target) <= band


def _schedule_core(order, body, from_states, is_reschedule):
    """Shared pipeline for schedule / reschedule after auth+shape+existence:
    OCC, order state, spec state, overlap, equipment fit, credit."""
    line = store.machine_lines.get(body["machine_line_id"])
    if line is None:
        raise_err(ERR_MACHINE_LINE_NOT_FOUND,
                  "MachineLine id does not resolve")
    # OCC (priority 5, before all other state rules)
    if body["expected_production_order_version"] != order["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_production_order_version does not equal the "
                  "order's current version")
    # order state
    check_terminal(order)
    if order["status"] not in from_states:
        raise_err(ERR_INVALID_STATE,
                  "Order cannot be scheduled from its current state")
    spec = store.bottle_specs.get(order["bottle_spec_id"])
    # spec must be QUALIFIED or PRODUCTION_ACTIVE
    if spec["status"] not in ("QUALIFIED", "PRODUCTION_ACTIVE"):
        raise_err(ERR_SPEC_NOT_QUALIFIED,
                  "Spec is not QUALIFIED or PRODUCTION_ACTIVE")
    # temporal: window + mold-change buffer; own CONFIRMED slots being
    # replaced are excluded
    mold = installed_mold_on_line(line["id"])
    new_mold_id = mold["id"] if mold else None
    exclude = set()
    if order["status"] == "SCHEDULED":
        exclude = {s["id"] for s in store.schedule_slots.values()
                   if s["production_order_id"] == order["id"]
                   and s["status"] == "CONFIRMED"}
    if schedule_conflict(line["id"], body["planned_start"],
                         body["planned_end"], new_mold_id, exclude):
        raise_err(ERR_SCHEDULE_OVERLAP,
                  "Window intersects another slot or violates the "
                  "mold-change buffer")
    # equipment fit
    if spec["label_type"] != "NONE" and not line["has_inline_labeler"]:
        raise_err(ERR_LABELER_REQUIRED,
                  "Spec requires inline labeling but the line has no labeler")
    if spec["diameter_mm"] > line["max_bottle_diameter_mm"]:
        raise_err(ERR_LABELER_REQUIRED,
                  "Bottle diameter exceeds the line's maximum")
    # fiscal: credit exposure
    customer = store.customers.get(order["customer_id"])
    if not credit_check(customer, order, spec):
        raise_err(ERR_CREDIT_LIMIT_EXCEEDED,
                  "Scheduling would exceed the customer's credit limit")
    # ---- apply ----
    if order["status"] == "SCHEDULED":
        # re-slotting supersedes the order's prior CONFIRMED slots
        cancel_slots_for_order(order)
    if is_reschedule:
        order["spec_revision_baseline"] = spec["content_revision"]
    order["status"] = "SCHEDULED"
    touch(order)
    create_slot(order, line, body["planned_start"], body["planned_end"])
    maybe_advance_spec(spec)
    return order


@bp.post("/production-orders")
def create_order():
    _, role = authenticate()
    require_role(role, ["ProductionScheduler"])
    body = check_fields(get_body(), {
        "bottle_spec_id": ("str", True),
        "quantity_ordered": ("int", True),
        "planned_weight_g": ("number", True),
        "logistics_mode": ("enum", False, {"WAREHOUSE", "BLOW_ON_SITE"}),
    })
    spec = store.bottle_specs.get(body["bottle_spec_id"])
    if spec is None:
        raise_err(ERR_BOTTLE_SPEC_NOT_FOUND, "BottleSpec id does not resolve")
    if not planned_weight_in_tolerance(spec, body["planned_weight_g"]):
        raise_err(ERR_PLANNED_WEIGHT_OUT_OF_TOLERANCE,
                  "planned_weight_g is outside the spec tolerance band")
    customer = store.customers.get(spec["customer_id"])
    order = {
        "bottle_spec_id": spec["id"],
        "customer_id": spec["customer_id"],
        "logistics_mode": body.get(
            "logistics_mode",
            customer["default_logistics_mode"] if customer else "WAREHOUSE"),
        "quantity_ordered": body["quantity_ordered"],
        "planned_weight_g": body["planned_weight_g"],
        "spec_revision_baseline": None,
        "status": "DRAFT",
    }
    stamp_new(order, new_id())
    store.production_orders[order["id"]] = order
    return success_object(ser_production_order(order), 201)


@bp.get("/production-orders")
def list_orders():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    customer_id = query_filter("customer_id")
    bottle_spec_id = query_filter("bottle_spec_id")
    status = query_filter("status", ORDER_STATUSES)
    limit, offset = pagination_params()
    rows = list(store.production_orders.values())
    if customer_id is not None:
        rows = [o for o in rows if o["customer_id"] == customer_id]
    if bottle_spec_id is not None:
        rows = [o for o in rows if o["bottle_spec_id"] == bottle_spec_id]
    if status is not None:
        rows = [o for o in rows if o["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_production_order(o) for o in page], limit,
                        offset, len(rows))


@bp.get("/production-orders/<oid>")
def get_order(oid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(ser_production_order(get_order_or_404(oid)))


@bp.get("/production-orders/<oid>/summary")
def order_summary(oid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    order = get_order_or_404(oid)
    rollups = order_rollups(order)
    return success_object({
        "quantity_produced": rollups["quantity_produced"],
        "quantity_good": rollups["quantity_good"],
        "quantity_scrapped": rollups["quantity_scrapped"],
        "quantity_accepted": rollups["quantity_accepted"],
        "quantity_qc_scrapped": rollups["quantity_qc_scrapped"],
        "quantity_reserved": rollups["quantity_reserved"],
        "quantity_shipped": rollups["quantity_shipped"],
        "quantity_unallocated": rollups["quantity_unallocated"],
    })


SCHEDULE_SCHEMA = {
    "machine_line_id": ("str", True),
    "planned_start": ("datetime", True),
    "planned_end": ("datetime", True),
    "expected_production_order_version": ("int", True),
}


def _parse_schedule_body():
    # shape (priority 3) precedes path existence (priority 4)
    body = check_fields(get_body(), SCHEDULE_SCHEMA)
    if body["planned_start"] >= body["planned_end"]:
        from errors import ERR_INVALID_REQUEST
        raise_err(ERR_INVALID_REQUEST,
                  "planned_start must be strictly before planned_end")
    return body


@bp.post("/production-orders/<oid>/schedule")
def schedule_order(oid):
    _, role = authenticate()
    require_role(role, ["ProductionScheduler"])
    body = _parse_schedule_body()
    order = get_order_or_404(oid)
    _schedule_core(order, body, ("DRAFT", "SCHEDULED"), is_reschedule=False)
    return success_object(ser_production_order(order))


@bp.post("/production-orders/<oid>/reschedule")
def reschedule_order(oid):
    _, role = authenticate()
    require_role(role, ["ProductionScheduler"])
    body = _parse_schedule_body()
    order = get_order_or_404(oid)
    _schedule_core(order, body, ("HELD",), is_reschedule=True)
    return success_object(ser_production_order(order))


@bp.post("/production-orders/<oid>/release")
def release_order(oid):
    _, role = authenticate()
    require_role(role, ["ProductionScheduler"])
    check_fields(get_body(), {})
    order = get_order_or_404(oid)
    check_terminal(order)
    if order["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Only a SCHEDULED order can be released")
    has_confirmed = any(
        s["production_order_id"] == order["id"] and s["status"] == "CONFIRMED"
        for s in store.schedule_slots.values())
    if not has_confirmed:
        raise_err(ERR_NO_ACTIVE_SLOT,
                  "Order has no ScheduleSlot in CONFIRMED")
    spec = store.bottle_specs.get(order["bottle_spec_id"])
    if spec["status"] not in ("QUALIFIED", "PRODUCTION_ACTIVE"):
        raise_err(ERR_SPEC_NOT_QUALIFIED,
                  "Spec is not QUALIFIED or PRODUCTION_ACTIVE")
    if spec["content_revision"] != spec["qualified_revision"]:
        raise_err(ERR_SPEC_REVISION_STALE,
                  "Spec content_revision no longer equals qualified_revision")
    # material gate: theoretical draw plus five percent uplift
    from decimal import Decimal
    required = (Decimal(order["quantity_ordered"]) * order["planned_weight_g"]
                / Decimal("1000") * Decimal("1.05"))
    if total_available(spec["resin_type"]) < required:
        raise_err(ERR_INSUFFICIENT_MATERIAL,
                  "Not enough RELEASED/IN_USE resin for the release check")
    order["spec_revision_baseline"] = spec["content_revision"]
    order["status"] = "RELEASED"
    touch(order)
    return success_object(ser_production_order(order))


@bp.post("/production-orders/<oid>/hold")
def hold_order_endpoint(oid):
    _, role = authenticate()
    require_role(role, ["QualityTechnician"])
    check_fields(get_body(), {})
    order = get_order_or_404(oid)
    check_terminal(order)
    if order["status"] != "RUNNING":
        raise_err(ERR_INVALID_STATE, "Only a RUNNING order can be held")
    hold_order(order)
    return success_object(ser_production_order(order))


@bp.post("/production-orders/<oid>/cancel")
def cancel_order_endpoint(oid):
    _, role = authenticate()
    require_role(role, ["ProductionScheduler"])
    check_fields(get_body(), {})
    order = get_order_or_404(oid)
    check_terminal(order)
    if order["status"] not in ("DRAFT", "SCHEDULED", "RELEASED", "HELD"):
        raise_err(ERR_INVALID_STATE,
                  "Order cannot be cancelled from its current state")
    order["status"] = "CANCELLED"
    touch(order)
    cancel_slots_for_order(order)
    return success_object(ser_production_order(order))


@bp.post("/production-orders/<oid>/complete")
def complete_order(oid):
    _, role = authenticate()
    require_role(role, ["ProductionScheduler"])
    check_fields(get_body(), {})
    order = get_order_or_404(oid)
    check_terminal(order)
    if order["status"] != "RUNNING":
        raise_err(ERR_INVALID_STATE, "Only a RUNNING order can be completed")
    for r in store.production_runs.values():
        if r["production_order_id"] == order["id"] and r["status"] == "OPEN":
            raise_err(ERR_INVALID_STATE,
                      "Order still has an OPEN production run")
    run_ids = {r["id"] for r in store.production_runs.values()
               if r["production_order_id"] == order["id"]}
    for lot in store.quality_test_lots.values():
        if (lot["production_run_id"] in run_ids
                and lot["status"] not in ("ACCEPTED", "SCRAPPED", "VOIDED")):
            raise_err(ERR_INVALID_STATE,
                      "Order has quality test lots that are not terminal")
    # find the line this order occupies BEFORE flipping its slots
    occupying_lines = [l for l in store.machine_lines.values()
                       if l["status"] == "RUNNING"
                       and occupying_order_id(l) == order["id"]]
    order["status"] = "COMPLETED"
    touch(order)
    for s in store.schedule_slots.values():
        if (s["production_order_id"] == order["id"]
                and s["status"] == "IN_PROGRESS"):
            s["status"] = "COMPLETED"
            touch(s)
    # line falls back from RUNNING to CHANGEOVER
    for l in occupying_lines:
        l["status"] = "CHANGEOVER"
        touch(l)
    return success_object(ser_production_order(order))


@bp.get("/production-orders/<oid>/schedule-slots")
def order_slots(oid):
    _, role = authenticate()
    require_role(role, SLOT_READ_ROLES)
    get_order_or_404(oid)
    status = query_filter("status", SLOT_STATUSES)
    limit, offset = pagination_params()
    rows = [s for s in store.schedule_slots.values()
            if s["production_order_id"] == oid]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    rows = sorted_rows(rows)
    page = rows[offset:offset + limit]
    return success_list([ser_schedule_slot(s) for s in page], limit, offset,
                        len(rows))
