"""Quote and RoutingOp routes (PRD §3.2, §3.4)."""
from flask import Blueprint, request

from db import db, lock, base_fields, touch
from errors import err
from middleware import require_roles, require_auth
from helpers import (
    get_body, require_fields, validate_enum, as_int, as_number, as_str,
    paginate, serialize, serialize_list,
)
from response import success, list_response
import calculations as calc
import services as svc

bp = Blueprint("quotes", __name__)

MACHINE_CLASSES = {"MILL_3AX", "MILL_5AX", "LATHE"}


def get_quote_or_404(quote_id):
    q = db.quotes.get(quote_id)
    if q is None:
        raise err("ERR_NOT_FOUND", "Quote not found")
    return q


def get_op_or_404(op_id):
    op = db.routing_ops.get(op_id)
    if op is None:
        raise err("ERR_NOT_FOUND", "RoutingOp not found")
    return op


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------


@bp.route("/quotes", methods=["POST"])
def create_quote():
    require_roles("Estimator")
    body = get_body()
    require_fields(body, "rfq_id", "part_line_id", "material_unit_cost_cents")
    rfq_id = as_str(body, "rfq_id")
    part_line_id = as_str(body, "part_line_id")
    material_unit_cost_cents = as_int(body, "material_unit_cost_cents")
    scrap = body.get("scrap_allowance_pct")
    if scrap is None:
        scrap = 0
    else:
        scrap = as_int(body, "scrap_allowance_pct", minimum=0, maximum=100)
    with lock():
        # existence: body FKs left to right (rfq_id then part_line_id)
        if rfq_id not in db.rfqs:
            raise err("ERR_NOT_FOUND", "RFQ not found")
        if part_line_id not in db.part_lines:
            raise err("ERR_NOT_FOUND", "PartLine not found")
        rec = base_fields()
        rec.update({
            "rfq_id": rfq_id,
            "part_line_id": part_line_id,
            "status": "DRAFT",
            "material_unit_cost_cents": material_unit_cost_cents,
            "scrap_allowance_pct": scrap,
            "margin_pct": 0,
            "extended_cost_cents": 0,
            "quoted_price_cents": 0,
            "quoted_unit_price_cents": 0,
            "rejection_reason": None,
        })
        db.quotes[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/quotes/<quote_id>", methods=["GET"])
def get_quote(quote_id):
    require_auth()
    with lock():
        return success(serialize(get_quote_or_404(quote_id)))


@bp.route("/quotes", methods=["GET"])
def list_quotes():
    require_auth()
    rfq_id = request.args.get("rfq_id")
    part_line_id = request.args.get("part_line_id")
    status = request.args.get("status")
    with lock():
        items = list(db.quotes.values())
        if rfq_id:
            items = [q for q in items if q["rfq_id"] == rfq_id]
        if part_line_id:
            items = [q for q in items if q["part_line_id"] == part_line_id]
        if status:
            items = [q for q in items if q["status"] == status]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/quotes/<quote_id>/price", methods=["POST"])
def price_quote(quote_id):
    require_roles("Estimator")
    with lock():
        quote = get_quote_or_404(quote_id)
        if quote["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "Quote must be DRAFT to price")
        ops = svc.routing_ops_for_quote(quote_id)
        if len(ops) < 1:
            raise err("ERR_QUOTE_NO_ROUTING", "Quote has no routing operations")
        rfq = db.rfqs.get(quote["rfq_id"])
        if rfq is None or rfq["status"] != "SUBMITTED":
            raise err("ERR_RFQ_NOT_SUBMITTED", "Owning RFQ is not SUBMITTED")
        pl = db.part_lines.get(quote["part_line_id"])
        quantity = pl["quantity"]
        result = calc.quote_estimate_cost(quote, ops, quantity)
        quote.update(result)
        quote["status"] = "PRICED"
        touch(quote)
        return success(serialize(quote))


@bp.route("/quotes/<quote_id>/approve", methods=["POST"])
def approve_quote(quote_id):
    require_roles("Estimator")
    body = get_body()
    with lock():
        quote = get_quote_or_404(quote_id)
        if quote["status"] != "PRICED":
            raise err("ERR_INVALID_STATE", "Quote must be PRICED to approve")
        # OCC (priority 6, before cross-entity)
        expected = body.get("expected_quote_version")
        if expected is not None and expected != quote["version"]:
            raise err("ERR_STALE_VERSION", "expected_quote_version does not match")
        quote["status"] = "APPROVED"
        touch(quote)
        # bubble-up: RFQ SUBMITTED -> QUOTED
        rfq = db.rfqs.get(quote["rfq_id"])
        if rfq is not None:
            svc.maybe_bubble_rfq_to_quoted(rfq)
        return success(serialize(quote))


@bp.route("/quotes/<quote_id>/reject", methods=["POST"])
def reject_quote(quote_id):
    require_roles("Estimator")
    body = get_body()
    with lock():
        quote = get_quote_or_404(quote_id)
        if quote["status"] != "PRICED":
            raise err("ERR_INVALID_STATE", "Quote must be PRICED to reject")
        reason = body.get("rejection_reason")
        if reason is not None and not isinstance(reason, str):
            raise err("ERR_INVALID_REQUEST", "rejection_reason must be a string")
        quote["status"] = "REJECTED"
        quote["rejection_reason"] = reason
        touch(quote)
        return success(serialize(quote))


@bp.route("/quotes/<quote_id>/reopen", methods=["POST"])
def reopen_quote(quote_id):
    require_roles("Estimator")
    with lock():
        quote = get_quote_or_404(quote_id)
        if quote["status"] != "REJECTED":
            raise err("ERR_INVALID_STATE", "Quote must be REJECTED to reopen")
        rfq = db.rfqs.get(quote["rfq_id"])
        if rfq is None or rfq["status"] != "SUBMITTED":
            raise err("ERR_RFQ_NOT_SUBMITTED", "Owning RFQ is not SUBMITTED")
        quote["status"] = "DRAFT"
        quote["margin_pct"] = 0
        quote["extended_cost_cents"] = 0
        quote["quoted_price_cents"] = 0
        quote["quoted_unit_price_cents"] = 0
        quote["rejection_reason"] = None
        touch(quote)
        return success(serialize(quote))


# ---------------------------------------------------------------------------
# RoutingOp
# ---------------------------------------------------------------------------


@bp.route("/quotes/<quote_id>/routing-ops", methods=["POST"])
def create_routing_op(quote_id):
    require_roles("Estimator")
    with lock():
        quote = get_quote_or_404(quote_id)
        body = get_body()
        require_fields(body, "seq", "machine_class", "estimated_cycle_min")
        seq = as_int(body, "seq", minimum=1)
        machine_class = body["machine_class"]
        validate_enum(machine_class, MACHINE_CLASSES, "machine_class")
        estimated_cycle_min = as_number(body, "estimated_cycle_min")
        setup_fee_cents = body.get("setup_fee_cents")
        if setup_fee_cents is None:
            setup_fee_cents = 0
        else:
            setup_fee_cents = as_int(body, "setup_fee_cents")
        if quote["status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "RoutingOps can only be added to a DRAFT Quote")
        rec = base_fields()
        rec.update({
            "quote_id": quote_id,
            "seq": seq,
            "machine_class": machine_class,
            "estimated_cycle_min": estimated_cycle_min,
            "actual_cycle_min": None,
            "setup_fee_cents": setup_fee_cents,
            "status": "PLANNED",
        })
        db.routing_ops[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/quotes/<quote_id>/routing-ops", methods=["GET"])
def list_quote_routing_ops(quote_id):
    require_auth()
    with lock():
        get_quote_or_404(quote_id)
        items = [o for o in db.routing_ops.values() if o["quote_id"] == quote_id]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/routing-ops", methods=["GET"])
def list_routing_ops():
    require_auth()
    quote_id = request.args.get("quote_id")
    status = request.args.get("status")
    with lock():
        items = list(db.routing_ops.values())
        if quote_id:
            items = [o for o in items if o["quote_id"] == quote_id]
        if status:
            items = [o for o in items if o["status"] == status]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/routing-ops/<op_id>", methods=["GET"])
def get_routing_op(op_id):
    require_auth()
    with lock():
        return success(serialize(get_op_or_404(op_id)))


@bp.route("/routing-ops/<op_id>/complete", methods=["POST"])
def complete_routing_op(op_id):
    require_roles("ShopAdmin")
    body = get_body()
    with lock():
        op = get_op_or_404(op_id)
        if op["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "RoutingOp must be SCHEDULED to complete")
        if "actual_cycle_min" not in body or body["actual_cycle_min"] is None:
            raise err("ERR_MISSING_ACTUAL_CYCLE", "actual_cycle_min is required")
        actual_cycle_min = as_number(body, "actual_cycle_min")
        op["status"] = "COMPLETED"
        op["actual_cycle_min"] = actual_cycle_min
        touch(op)
        # recompute WorkOrder.actual_cost_cents for the WO(s) of this quote
        for wo in svc.work_orders_for_quote(op["quote_id"]):
            svc.recompute_work_order_actual_cost(wo)
            touch(wo)
        return success(serialize(op))
