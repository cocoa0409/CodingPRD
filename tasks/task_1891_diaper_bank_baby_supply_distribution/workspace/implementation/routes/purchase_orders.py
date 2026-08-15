"""Purchase order endpoints: wholesale purchasing under segregation of duties
(PRD §2.11, §3.3)."""

from flask import request

from db import store, base_fields, touch, now
from errors import (ERR_NOT_FOUND, ERR_VALIDATION, ERR_PO_NOT_SUBMITTABLE,
                    ERR_PO_NOT_RECEIVABLE, ERR_GRANT_NOT_ACTIVE,
                    ERR_SOD_VIOLATION, ERR_GRANT_RESTRICTION_VIOLATION,
                    ERR_GRANT_BUDGET_EXCEEDED, raise_err)
from middleware import authenticate, require_role
from response import success_object, get_body, paginate
from serialize import po_json, grant_funds
from services.calc import po_total_cents, intake_valuation_cents
from validate import req_str, req_po_lines, req_quantity_lines
from . import make_blueprint

bp = make_blueprint("purchase_orders")

READ_ROLES = ["WarehouseManager", "FinanceManager", "BankAdmin"]


def _get_po_or_404(po_id):
    po = store.purchase_orders.get(po_id)
    if po is None:
        raise_err(ERR_NOT_FOUND, "Purchase order not found.")
    return po


def _require_inventory():
    inv = store.inventory
    if inv is None or not inv["initialized"]:
        raise_err(ERR_VALIDATION, "Inventory has not been initialized.")
    return inv


@bp.route("/purchase-orders", methods=["POST"])
def create_po():
    uid, role = authenticate()
    require_role(role, ["WarehouseManager"])
    body = get_body()
    grant_id = body.get("grant_id")
    if not isinstance(grant_id, str) or grant_id not in store.grants:
        raise_err(ERR_VALIDATION, "grant_id must reference an existing grant.")
    vendor = req_str(body, "vendor_name")
    lines = req_po_lines(body, "lines")
    discount = body.get("discount_pct", 0)
    if discount is None:
        discount = 0
    if (not isinstance(discount, (int, float)) or isinstance(discount, bool)
            or not (0 <= discount < 1)):
        raise_err(ERR_VALIDATION, "discount_pct must be a number with 0 <= x < 1.")
    po = base_fields()
    po.update({
        "grant_id": grant_id,
        "vendor_name": vendor,
        "lines": lines,
        "discount_pct": discount,
        "total_cost_cents": po_total_cents(lines, discount),
        "status": "DRAFT",
        "created_by_user_id": uid,
        "submitted_by_user_id": None,
        "received_intake_batch_id": None,
    })
    store.purchase_orders[po["id"]] = po
    return success_object(po_json(po), status=201)


@bp.route("/purchase-orders", methods=["GET"])
def list_pos():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    grant_id = request.args.get("grant_id")
    status = request.args.get("status")
    batch_id = request.args.get("received_intake_batch_id")
    items = [po for po in store.purchase_orders.values()
             if (grant_id is None or po["grant_id"] == grant_id)
             and (status is None or po["status"] == status)
             and (batch_id is None or po["received_intake_batch_id"] == batch_id)]
    items.sort(key=lambda po: po["created_at"])
    return paginate([po_json(po) for po in items])


@bp.route("/purchase-orders/<po_id>", methods=["GET"])
def get_po(po_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(po_json(_get_po_or_404(po_id)))


@bp.route("/purchase-orders/<po_id>/submit", methods=["POST"])
def submit_po(po_id):
    uid, role = authenticate()
    require_role(role, ["FinanceManager"])
    po = _get_po_or_404(po_id)
    grant = store.grants[po["grant_id"]]
    # Five checks in the declared order (PRD §3.3).
    if po["status"] != "DRAFT":
        raise_err(ERR_PO_NOT_SUBMITTABLE, "Only a DRAFT order can be submitted.")
    if grant["status"] != "ACTIVE":
        raise_err(ERR_GRANT_NOT_ACTIVE, "The referenced grant is not ACTIVE.")
    if uid == po["created_by_user_id"]:
        raise_err(ERR_SOD_VIOLATION,
                  "The submitter must differ from the order's creator.")
    if grant["restriction"] == "OPERATIONS_ONLY":
        raise_err(ERR_GRANT_RESTRICTION_VIOLATION,
                  "Product purchases may not be submitted against an "
                  "OPERATIONS_ONLY grant.")
    _, _, available = grant_funds(grant)
    if po["total_cost_cents"] > available:
        raise_err(ERR_GRANT_BUDGET_EXCEEDED,
                  "Order total exceeds the grant's available funds.")
    po["status"] = "SUBMITTED"
    po["submitted_by_user_id"] = uid
    touch(po)
    touch(grant)
    return success_object(po_json(po))


@bp.route("/purchase-orders/<po_id>/receive", methods=["POST"])
def receive_po(po_id):
    _, role = authenticate()
    require_role(role, ["WarehouseManager"])
    po = _get_po_or_404(po_id)
    grant = store.grants[po["grant_id"]]
    if po["status"] != "SUBMITTED":
        raise_err(ERR_PO_NOT_RECEIVABLE,
                  "Only a SUBMITTED order can be received.")
    if grant["status"] != "ACTIVE":
        raise_err(ERR_GRANT_NOT_ACTIVE, "The referenced grant is not ACTIVE.")
    body = get_body()
    received = req_quantity_lines(body, "received_lines")
    # received sizes must be exactly the set of sizes present in po.lines.
    if set(ln["size_code"] for ln in received) != set(ln["size_code"] for ln in po["lines"]):
        raise_err(ERR_VALIDATION,
                  "received_lines sizes must exactly match the order's sizes.")
    inv = _require_inventory()
    # committed -> spent happens automatically via the status flip; the intake
    # batch is born POSTED and deposits stock.
    b = base_fields()
    b.update({
        "source_type": "PURCHASE",
        "donor_name": None,
        "purchase_order_id": po["id"],
        "lines": received,
        "valued_total_cents": intake_valuation_cents(received, "PURCHASE", po),
        "status": "POSTED",
        "posted_at": now(),
    })
    store.intake_batches[b["id"]] = b
    for ln in received:
        inv["sizes"][ln["size_code"]]["on_hand_units"] += ln["quantity"]
    po["status"] = "RECEIVED"
    po["received_intake_batch_id"] = b["id"]
    touch(po)
    # Auto-exhaustion: equality exhausts (PRD §3.3). One version increment per
    # resource per request covers both the funds move and the status flip.
    _, spent, _ = grant_funds(grant)
    if spent >= grant["total_amount_cents"]:
        grant["status"] = "EXHAUSTED"
    touch(grant)
    touch(inv)
    return success_object(po_json(po))


@bp.route("/purchase-orders/<po_id>/cancel", methods=["POST"])
def cancel_po(po_id):
    _, role = authenticate()
    require_role(role, ["WarehouseManager", "FinanceManager"])
    po = _get_po_or_404(po_id)
    # Cancellation is symmetric with authority (PRD §2.11): WarehouseManager
    # cancels only DRAFT; FinanceManager cancels only SUBMITTED.
    if role == "WarehouseManager":
        if po["status"] != "DRAFT":
            raise_err(ERR_PO_NOT_SUBMITTABLE,
                      "WarehouseManager may only cancel a DRAFT order.")
    else:
        if po["status"] != "SUBMITTED":
            raise_err(ERR_PO_NOT_SUBMITTABLE,
                      "FinanceManager may only cancel a SUBMITTED order.")
    was_submitted = po["status"] == "SUBMITTED"
    po["status"] = "CANCELLED"
    touch(po)
    if was_submitted:
        # Release of committed funds happens via the status flip; bump grant.
        grant = store.grants[po["grant_id"]]
        touch(grant)
    return success_object(po_json(po))
