"""WorkOrder routes incl. material allocation, release, cancel cascade.

PRD §3.3 (work orders + material), §3.4 (actual cost).
"""
from flask import Blueprint, request

from db import db, lock, base_fields, touch
from errors import err
from middleware import require_roles, require_auth
from helpers import (
    get_body, require_fields, as_int, as_str,
    paginate, serialize, serialize_list,
)
from response import success, list_response
import services as svc

bp = Blueprint("work_orders", __name__)


def get_wo_or_404(wo_id):
    wo = db.work_orders.get(wo_id)
    if wo is None:
        raise err("ERR_NOT_FOUND", "WorkOrder not found")
    return wo


# ---------------------------------------------------------------------------
# WorkOrder CRUD
# ---------------------------------------------------------------------------


@bp.route("/work-orders", methods=["POST"])
def create_work_order():
    require_roles("ShopAdmin")
    body = get_body()
    require_fields(body, "quote_id", "part_line_id", "qty_ordered", "qty_started")
    quote_id = as_str(body, "quote_id")
    part_line_id = as_str(body, "part_line_id")
    qty_ordered = as_int(body, "qty_ordered", minimum=1)
    qty_started = as_int(body, "qty_started", minimum=0)
    with lock():
        # existence: body FKs left to right
        if quote_id not in db.quotes:
            raise err("ERR_NOT_FOUND", "Quote not found")
        if part_line_id not in db.part_lines:
            raise err("ERR_NOT_FOUND", "PartLine not found")
        rec = base_fields()
        rec.update({
            "quote_id": quote_id,
            "part_line_id": part_line_id,
            "qty_ordered": qty_ordered,
            "qty_started": qty_started,
            "qty_in_process": 0,
            "qty_accepted": 0,
            "qty_rework_pending": 0,
            "qty_scrapped": 0,
            "qty_shipped": 0,
            "status": "PLANNED",
            "material_allocated": False,
            "actual_cost_cents": 0,
        })
        db.work_orders[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/work-orders/<wo_id>", methods=["GET"])
def get_work_order(wo_id):
    require_auth()
    with lock():
        return success(serialize(get_wo_or_404(wo_id)))


@bp.route("/work-orders", methods=["GET"])
def list_work_orders():
    require_auth()
    quote_id = request.args.get("quote_id")
    part_line_id = request.args.get("part_line_id")
    status = request.args.get("status")
    with lock():
        items = list(db.work_orders.values())
        if quote_id:
            items = [w for w in items if w["quote_id"] == quote_id]
        if part_line_id:
            items = [w for w in items if w["part_line_id"] == part_line_id]
        if status:
            items = [w for w in items if w["status"] == status]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Material allocation (FIFO waterfall) — PRD §3.3
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<wo_id>/allocate-material", methods=["POST"])
def allocate_material(wo_id):
    require_roles("MaterialController")
    with lock():
        wo = get_wo_or_404(wo_id)
        pl = db.part_lines.get(wo["part_line_id"])
        spec = pl["material_spec"]
        need = wo["qty_started"]

        # Candidate AVAILABLE lots of the spec, FIFO by received_at ASC then
        # created_at ASC (never id).
        candidates = [
            l for l in db.material_lots.values()
            if l["status"] == "AVAILABLE" and l["material_spec"] == spec
        ]
        candidates.sort(key=lambda l: (l["received_at"], l["created_at"], l["_seq"]))

        draws = []  # (lot, take)
        remaining = need
        for lot in candidates:
            if remaining <= 0:
                break
            take = min(remaining, lot["qty_remaining"])
            if take > 0:
                draws.append((lot, take))
                remaining -= take

        if remaining > 0:
            # roll back: we haven't committed anything yet, just refuse
            raise err("ERR_INSUFFICIENT_MATERIAL", "Insufficient material to cover qty_started")

        # commit draws
        for lot, take in draws:
            alloc = base_fields()
            alloc.update({
                "work_order_id": wo_id,
                "material_lot_id": lot["id"],
                "qty_allocated": take,
                "status": "ACTIVE",
            })
            db.lot_allocations[alloc["id"]] = alloc
            lot["qty_remaining"] -= take
            if lot["qty_remaining"] == 0:
                lot["status"] = "DEPLETED"
            touch(lot)

        wo["material_allocated"] = True
        svc.recompute_work_order_actual_cost(wo)
        touch(wo)
        return success(serialize(wo))


# ---------------------------------------------------------------------------
# Release (OCC-guarded, cross-entity gated) — PRD §3.3
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<wo_id>/release", methods=["POST"])
def release_work_order(wo_id):
    require_roles("ShopAdmin")
    body = get_body()
    with lock():
        wo = get_wo_or_404(wo_id)
        if wo["status"] != "PLANNED":
            raise err("ERR_INVALID_STATE", "WorkOrder must be PLANNED to release")
        # OCC (priority 6) before cross-entity preconditions (priority 7)
        expected = body.get("expected_work_order_version")
        if expected is not None and expected != wo["version"]:
            raise err("ERR_STALE_VERSION", "expected_work_order_version does not match")
        # cross-entity: quote approved
        quote = db.quotes.get(wo["quote_id"])
        if quote is None or quote["status"] != "APPROVED":
            raise err("ERR_QUOTE_NOT_APPROVED", "Owning Quote is not APPROVED")
        # material allocated
        if not wo["material_allocated"]:
            raise err("ERR_MATERIAL_NOT_ALLOCATED", "Material not allocated")
        # qty_started >= qty_ordered
        if wo["qty_started"] < wo["qty_ordered"]:
            raise err("ERR_INVALID_QTY_STARTED", "qty_started must be >= qty_ordered")
        wo["status"] = "RELEASED"
        wo["qty_in_process"] = wo["qty_started"]
        touch(wo)
        return success(serialize(wo))


# ---------------------------------------------------------------------------
# Close — PRD §3.7
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<wo_id>/close", methods=["POST"])
def close_work_order(wo_id):
    require_roles("ShopAdmin")
    with lock():
        wo = get_wo_or_404(wo_id)
        if wo["status"] != "SHIPPED":
            raise err("ERR_INVALID_STATE", "WorkOrder must be SHIPPED to close")
        # every Invoice for this WO's shipments must be PAID
        for inv in svc.invoices_for_wo(wo_id):
            if inv["status"] != "PAID":
                raise err("ERR_INVOICE_UNPAID", "An invoice for this WO is not PAID")
        wo["status"] = "CLOSED"
        touch(wo)
        return success(serialize(wo))


# ---------------------------------------------------------------------------
# Cancel (compensation cascade) — PRD §3.3
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<wo_id>/cancel", methods=["POST"])
def cancel_work_order(wo_id):
    require_roles("ShopAdmin")
    with lock():
        wo = get_wo_or_404(wo_id)
        if wo["status"] not in ("PLANNED", "RELEASED"):
            raise err("ERR_INVALID_STATE", "WorkOrder can only be cancelled from PLANNED or RELEASED")
        if wo["status"] == "RELEASED":
            # no inspection may be DISPOSITIONED
            for insp in svc.inspections_for_wo(wo_id):
                if insp["status"] == "DISPOSITIONED":
                    raise err("ERR_WO_ALREADY_INSPECTED", "WorkOrder already has a dispositioned inspection")
            # compensation cascade
            # 1. void ACTIVE lot allocations, restore lot qty_remaining
            for alloc in svc.active_allocations_for_wo(wo_id):
                alloc["status"] = "VOIDED"
                touch(alloc)
                lot = db.material_lots.get(alloc["material_lot_id"])
                if lot is not None:
                    was_depleted = lot["status"] == "DEPLETED"
                    lot["qty_remaining"] += alloc["qty_allocated"]
                    if was_depleted and lot["qty_remaining"] > 0:
                        lot["status"] = "AVAILABLE"
                    touch(lot)
            # 2. release BOOKED machine slots on this WO's routing ops; revert ops
            op_ids = {o["id"] for o in svc.routing_ops_for_quote(wo["quote_id"])}
            for slot in db.machine_slots.values():
                if slot["status"] == "BOOKED" and slot["routing_op_id"] in op_ids:
                    slot["status"] = "RELEASED"
                    touch(slot)
                    op = db.routing_ops.get(slot["routing_op_id"])
                    if op is not None and op["status"] == "SCHEDULED":
                        op["status"] = "PLANNED"
                        touch(op)
            wo["qty_in_process"] = 0
            wo["material_allocated"] = False
        wo["status"] = "CANCELLED"
        touch(wo)
        return success(serialize(wo))


# ---------------------------------------------------------------------------
# Sub-resource lists
# ---------------------------------------------------------------------------


@bp.route("/work-orders/<wo_id>/lot-allocations", methods=["GET"])
def list_wo_lot_allocations(wo_id):
    require_auth()
    with lock():
        get_wo_or_404(wo_id)
        items = [a for a in db.lot_allocations.values() if a["work_order_id"] == wo_id]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/work-orders/<wo_id>/inspections", methods=["GET"])
def list_wo_inspections(wo_id):
    require_auth()
    with lock():
        get_wo_or_404(wo_id)
        items = [i for i in db.inspections.values() if i["work_order_id"] == wo_id]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)
