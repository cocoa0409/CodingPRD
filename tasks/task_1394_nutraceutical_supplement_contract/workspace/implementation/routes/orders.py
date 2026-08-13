"""Manufacturing orders: placement, cancellation, scheduling (PRD 3.3)."""
from flask import Blueprint, request

from db import store, new_entity, touch
from errors import (
    raise_error,
    ERR_NOT_RESOURCE_OWNER,
    ERR_FORMULA_STATE,
    ERR_ORDER_STATE,
    ERR_BELOW_MINIMUM_ORDER,
    ERR_LINE_SCHEDULE_CONFLICT,
)
from middleware import require_roles, ANY_ROLE
from response import ok
from services import batch_of_mo, refresh_customer_aggregates
from util import (
    body,
    invalid,
    is_int,
    not_found,
    paginate,
    parse_dt,
    req_str,
    sorted_by_created,
)

bp = Blueprint("orders", __name__)


@bp.post("/api/manufacturing-orders")
@require_roles("BrandRep")
def place_order(user_id, role):
    data = body()
    # Ownership (PRD 2.9 step 3): BrandRep's X-User-ID equals payload customer_id.
    customer_id = data.get("customer_id")
    if customer_id != user_id:
        raise_error(
            ERR_NOT_RESOURCE_OWNER,
            "BrandRep may only place orders for their own customer id",
        )
    customer = store["customers"].get(customer_id)
    if customer is None:
        not_found("customer_id does not identify an existing customer")
    formula_id = data.get("formula_id")
    formula = store["formulas"].get(formula_id) if isinstance(formula_id, str) else None
    if formula is None:
        not_found("formula_id does not identify an existing formula")
    if formula["status"] != "APPROVED":
        raise_error(ERR_FORMULA_STATE, "The ordered formula must be APPROVED at placement")
    ordered_qty = data.get("ordered_qty")
    if not is_int(ordered_qty):
        invalid("'ordered_qty' must be an integer")
    # Fiscal check last among business rules (PRD 2.9 step 13).
    if ordered_qty < formula["min_order_qty"]:
        raise_error(
            ERR_BELOW_MINIMUM_ORDER,
            "ordered_qty is below the formula's min_order_qty",
        )
    # Tiered, flat-rate pricing: greatest min_qty <= ordered_qty, lower bounds
    # inclusive; the selected tier's rate applies to every unit.
    eligible = [t for t in formula["price_tiers"] if t["min_qty"] <= ordered_qty]
    selected = max(eligible, key=lambda t: t["min_qty"])
    unit_price = selected["unit_price_cents"]
    total_price = ordered_qty * unit_price
    order = new_entity({
        "customer_id": customer_id,
        "formula_id": formula_id,
        "formula_version_at_order": formula["version"],
        "ordered_qty": ordered_qty,
        "unit_price_cents": unit_price,
        "total_price_cents": total_price,
        "recall_flag": False,
        "status": "PLACED",
    })
    store["manufacturing_orders"][order["id"]] = order
    refresh_customer_aggregates(customer_id)
    return ok(order, 201)


@bp.get("/api/manufacturing-orders")
@require_roles(*ANY_ROLE)
def list_orders(user_id, role):
    items = list(store["manufacturing_orders"].values())
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    formula_id = request.args.get("formula_id")
    if formula_id is not None:
        items = [o for o in items if o["formula_id"] == formula_id]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/api/manufacturing-orders/<order_id>")
@require_roles(*ANY_ROLE)
def get_order(user_id, role, order_id):
    order = store["manufacturing_orders"].get(order_id)
    if order is None:
        not_found()
    return ok(order)


@bp.post("/api/manufacturing-orders/<order_id>/cancel")
@require_roles("BrandRep")
def cancel_order(user_id, role, order_id):
    order = store["manufacturing_orders"].get(order_id)
    if order is None:
        not_found()
    if order["customer_id"] != user_id:
        raise_error(
            ERR_NOT_RESOURCE_OWNER,
            "BrandRep may only cancel their own orders",
        )
    if order["status"] not in ("PLACED", "SCHEDULED"):
        raise_error(
            ERR_ORDER_STATE,
            "Only a PLACED or SCHEDULED order may be cancelled",
        )
    was = order["status"]
    order["status"] = "CANCELLED"
    touch(order)
    if was == "SCHEDULED":
        batch = batch_of_mo(order["id"])
        if batch is not None and batch["production_status"] != "CANCELLED":
            batch["production_status"] = "CANCELLED"
            touch(batch)
    refresh_customer_aggregates(order["customer_id"])
    return ok(order)


@bp.post("/api/manufacturing-orders/<order_id>/schedule")
@require_roles("ProductionPlanner")
def schedule_order(user_id, role, order_id):
    order = store["manufacturing_orders"].get(order_id)
    if order is None:
        not_found()
    if order["status"] != "PLACED":
        raise_error(ERR_ORDER_STATE, "Only a PLACED order may be scheduled")
    data = body()
    production_line_id = req_str(data, "production_line_id")
    line = store["production_lines"].get(production_line_id)
    if line is None:
        not_found("production_line_id does not identify an existing production line")
    planned_start_raw = req_str(data, "planned_start")
    planned_end_raw = req_str(data, "planned_end")
    planned_start = parse_dt(planned_start_raw, "planned_start")
    planned_end = parse_dt(planned_end_raw, "planned_end")
    # Half-open window intersection: adjacency is lawful (PRD 3.3).
    for other in store["batches"].values():
        if other["production_line_id"] != production_line_id:
            continue
        if other["production_status"] == "CANCELLED":
            continue
        other_start = parse_dt(other["planned_start"])
        other_end = parse_dt(other["planned_end"])
        if planned_start < other_end and other_start < planned_end:
            raise_error(
                ERR_LINE_SCHEDULE_CONFLICT,
                "The planned window intersects an existing batch window on this line",
            )
    if not planned_start < planned_end:
        invalid("planned_start must be strictly before planned_end")
    formula = store["formulas"].get(order["formula_id"])
    batch = new_entity({
        "mo_id": order["id"],
        "production_line_id": production_line_id,
        "theoretical_units": formula["batch_size_units"],
        "planned_start": planned_start_raw,
        "planned_end": planned_end_raw,
        "actual_yield_units": None,
        "actual_bulk_mass_g": None,
        "yield_variance_pct": None,
        "completed_at": None,
        "recorded_by_id": None,
        "reviewed_by_id": None,
        "expiry_date": None,
        "production_status": "CREATED",
        "quality_status": "PENDING_QC",
    })
    store["batches"][batch["id"]] = batch
    order["status"] = "SCHEDULED"
    touch(order)
    return ok(batch, 201)
