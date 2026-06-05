"""Work-order lifecycle endpoints (PRD §3.4, §3.9, §3.10)."""
from flask import Blueprint, request

import db
import errors
import lookups
import validators as V
from middleware import authenticate, authorize, get_json_body
from response import object_response, array_response
from serialize import public, public_list
from services import calc

bp = Blueprint("work_orders", __name__)


def _recompute_wip(wo):
    wo["wip_qty"] = wo["started_qty"] - wo["completed_qty"] - wo["scrapped_qty"]


@bp.route("/work-orders", methods=["POST"])
def create_work_order():
    _, role = authenticate()
    authorize(role, ["ProductionPlanner", "PlantAdmin"])
    body = get_json_body()

    product_id = V.as_string(V.require(body, "product_id"), "product_id")
    routing_id = V.as_string(V.require(body, "routing_id"), "routing_id")
    order_qty = V.as_int(V.require(body, "order_qty"), "order_qty")

    with db.LOCK:
        lookups.product(product_id)
        lookups.routing(routing_id)
        if order_qty <= 0:
            raise errors.invalid_request("order_qty must be > 0.")
        rec = db.new_record()
        rec.update({
            "product_id": product_id,
            "routing_id": routing_id,
            "order_qty": order_qty,
            "status": "PLANNED",
            "started_qty": 0,
            "completed_qty": 0,
            "scrapped_qty": 0,
            "wip_qty": 0,
            "material_variance_cents": 0,
        })
        db.work_orders[rec["id"]] = rec
        return object_response(public(rec), 201)


@bp.route("/work-orders/<rid>", methods=["GET"])
def get_work_order(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    return object_response(public(lookups.work_order(rid)))


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    limit, offset = V.parse_pagination(request.args)
    product_id = request.args.get("product_id")
    routing_id = request.args.get("routing_id")
    status = request.args.get("status")
    rows = list(db.work_orders.values())
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if routing_id is not None:
        rows = [r for r in rows if r["routing_id"] == routing_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.route("/work-orders/<rid>/release", methods=["POST"])
def release_work_order(rid):
    _, role = authenticate()
    authorize(role, ["ProductionPlanner", "PlantAdmin"])
    body = get_json_body()
    with db.LOCK:
        wo = lookups.work_order(rid)

        # State (priority 4): release only defined from PLANNED.
        if wo["status"] != "PLANNED":
            raise errors.invalid_state("Only a PLANNED work order may be released.")

        routing = lookups.routing(wo["routing_id"])

        # ERR_ROUTING_NOT_RELEASED (priority 6) precedes OCC (priority 16).
        if routing["status"] != "RELEASED":
            raise errors.ApiError(errors.ERR_ROUTING_NOT_RELEASED,
                                  "Referenced routing is not RELEASED.", 409)
        # Routing must build this product.
        if routing["product_id"] != wo["product_id"]:
            raise errors.ApiError(errors.ERR_ROUTING_NOT_RELEASED,
                                  "Routing does not build this work order's product.", 409)

        # OCC (priority 16): expected_work_order_version required and must match.
        expected = V.require(body, "expected_work_order_version")
        expected = V.as_int(expected, "expected_work_order_version")
        if expected != wo["version"]:
            raise errors.ApiError(errors.ERR_STALE_VERSION,
                                  "expected_work_order_version does not match.", 412)

        # --- Cascade hop 1+2: explode BOM into ComponentDemand rows ---
        exploded = calc.explode_bom(wo["product_id"], wo["order_qty"])
        for component_id, required_qty in exploded:
            product = db.products.get(component_id)
            unit_cost = product["unit_cost_cents"] if product else 0
            std_cost = calc.standard_cost_for(required_qty, unit_cost)
            demand = db.new_record()
            demand.update({
                "work_order_id": wo["id"],
                "component_product_id": component_id,
                "required_qty": float(required_qty),
                "issued_qty": 0,
                "standard_cost_cents": std_cost,
            })
            db.component_demands[demand["id"]] = demand

        # --- Cascade hop 3: one WorkOrderOperation per Operation, seq order ---
        ops = [o for o in db.operations.values() if o["routing_id"] == routing["id"]]
        ops.sort(key=lambda o: (o["sequence_no"], o.get("_seq", 0)))
        for op in ops:
            wop = db.new_record()
            wop.update({
                "work_order_id": wo["id"],
                "operation_id": op["id"],
                "machine_id": op["machine_id"],
                "sequence_no": op["sequence_no"],
                "status": "QUEUED",
                "units_in": 0,
                "good_qty": 0,
                "scrap_qty": 0,
                "scheduled_start": None,
                "scheduled_end": None,
            })
            db.work_order_operations[wop["id"]] = wop

        wo["status"] = "RELEASED"
        db.touch(wo)
        return object_response(public(wo))


@bp.route("/work-orders/<rid>/complete", methods=["POST"])
def complete_work_order(rid):
    _, role = authenticate()
    authorize(role, ["ProductionPlanner", "PlantAdmin"])
    with db.LOCK:
        wo = lookups.work_order(rid)
        if wo["status"] != "IN_PROCESS":
            raise errors.invalid_state("Only an IN_PROCESS work order may be completed.")
        # precondition: every WorkOrderOperation COMPLETED and wip_qty == 0.
        wops = [w for w in db.work_order_operations.values() if w["work_order_id"] == rid]
        if any(w["status"] != "COMPLETED" for w in wops):
            raise errors.invalid_state("All operations must be COMPLETED to complete the order.")
        if wo["wip_qty"] != 0:
            raise errors.invalid_state("wip_qty must be 0 to complete the order.")

        # finalize consumed Lot.issued_qty (already maintained at issue time;
        # this is the sealing point) and seal genealogy links for the order.
        # compute material_variance_cents
        wo["material_variance_cents"] = calc.material_variance(rid)
        wo["status"] = "COMPLETED"
        db.touch(wo)
        return object_response(public(wo))


@bp.route("/work-orders/<rid>/close", methods=["POST"])
def close_work_order(rid):
    _, role = authenticate()
    authorize(role, ["ProductionPlanner", "PlantAdmin"])
    with db.LOCK:
        wo = lookups.work_order(rid)
        if wo["status"] != "COMPLETED":
            raise errors.invalid_state("Only a COMPLETED work order may be closed.")
        # precondition: no ScrapDisposition for this order is PENDING.
        for sd in db.scrap_dispositions.values():
            wop = db.work_order_operations.get(sd["work_order_operation_id"])
            if wop and wop["work_order_id"] == rid and sd["status"] == "PENDING":
                raise errors.invalid_state("A pending scrap disposition blocks closing.")
        wo["status"] = "CLOSED"
        db.touch(wo)
        return object_response(public(wo))


@bp.route("/work-orders/<rid>/cancel", methods=["POST"])
def cancel_work_order(rid):
    _, role = authenticate()
    authorize(role, ["ProductionPlanner", "PlantAdmin"])
    with db.LOCK:
        wo = lookups.work_order(rid)
        status = wo["status"]
        if status == "PLANNED":
            wo["status"] = "CANCELLED"
            db.touch(wo)
            return object_response(public(wo))
        if status == "RELEASED":
            # precondition: no WorkOrderOperation for this order is IN_PROGRESS.
            for w in db.work_order_operations.values():
                if w["work_order_id"] == rid and w["status"] == "IN_PROGRESS":
                    raise errors.invalid_state(
                        "Cannot cancel: an operation is IN_PROGRESS.")
            # reverse every non-reversed LotIssue, restoring Lot.on_hand_qty.
            for issue in db.lot_issues.values():
                demand = db.component_demands.get(issue["component_demand_id"])
                if demand is None or demand["work_order_id"] != rid:
                    continue
                if issue.get("reversed"):
                    continue
                lot = db.lots.get(issue["lot_id"])
                if lot is not None:
                    lot["on_hand_qty"] = lot["on_hand_qty"] + issue["issued_qty"]
                    lot["issued_qty"] = lot["issued_qty"] - issue["issued_qty"]
                    db.touch(lot)
                demand["issued_qty"] = demand["issued_qty"] - issue["issued_qty"]
                db.touch(demand)
                issue["reversed"] = True
                db.touch(issue)
            # delete ComponentDemand rows for this order.
            to_delete = [d_id for d_id, d in db.component_demands.items()
                         if d["work_order_id"] == rid]
            for d_id in to_delete:
                del db.component_demands[d_id]
            wo["status"] = "CANCELLED"
            db.touch(wo)
            return object_response(public(wo))
        raise errors.invalid_state("Work order cannot be cancelled from its current state.")


@bp.route("/work-orders/<rid>/cost-summary", methods=["GET"])
def cost_summary(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "PlantAdmin"])
    with db.LOCK:
        lookups.work_order(rid)
        bom_standard = calc.standard_total_cost(rid)
        actual = calc.actual_material_cost(rid)
        labor = calc.labor_total_cost(rid)
        variance = actual - bom_standard
        return object_response({
            "bom_standard_total_cents": bom_standard,
            "actual_cost_cents": actual,
            "labor_total_cents": labor,
            "material_variance_cents": variance,
        })


# --- Reverse-reachability listings rooted on a work order -------------------
@bp.route("/work-orders/<rid>/component-demands", methods=["GET"])
def list_wo_component_demands(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator", "PlantAdmin"])
    lookups.work_order(rid)
    limit, offset = V.parse_pagination(request.args)
    rows = [d for d in db.component_demands.values() if d["work_order_id"] == rid]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.route("/work-orders/<rid>/operations", methods=["GET"])
def list_wo_operations(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "MachineOperator",
                     "QualityInspector", "PlantAdmin"])
    lookups.work_order(rid)
    limit, offset = V.parse_pagination(request.args)
    rows = [w for w in db.work_order_operations.values() if w["work_order_id"] == rid]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)


@bp.route("/work-orders/<rid>/genealogy", methods=["GET"])
def list_wo_genealogy(rid):
    _, role = authenticate()
    authorize(role, ["ManufacturingEngineer", "ProductionPlanner", "QualityInspector", "PlantAdmin"])
    lookups.work_order(rid)
    limit, offset = V.parse_pagination(request.args)
    rows = [g for g in db.genealogy_links.values() if g["work_order_id"] == rid]
    page, total = V.paginate(rows, limit, offset)
    return array_response(public_list(page), limit, offset, total)
