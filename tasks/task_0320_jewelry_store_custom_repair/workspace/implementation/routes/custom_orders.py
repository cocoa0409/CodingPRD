"""Custom-design order lifecycle (PRD §3.3)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_caller, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.calc import (
    provisional_total_cents, deposit_required_cents, final_total_cents, MAX_REVISIONS,
)
from services.common import (
    get_body, require_str, require_int, resolve_fk, resolve_path, require_own_version,
    post_ledger_entry,
)

bp = Blueprint("custom_orders", __name__)


def recompute_deposit_paid(order):
    total = 0
    for p in db.payments.values():
        if p["target_type"] == "CUSTOM_ORDER" and p.get("custom_order_id") == order["id"] \
                and p["outcome"] == "SUCCEEDED":
            total += p["amount_cents"]
    order["deposit_paid_cents"] = total
    return total


def recompute_balance(order):
    """pre-production: provisional - deposit_paid; post complete-production: final - deposit_paid."""
    deposit_paid = order["deposit_paid_cents"]
    if order.get("final_total_cents") is not None:
        order["balance_due_cents"] = order["final_total_cents"] - deposit_paid
    elif order.get("provisional_total_cents") is not None:
        order["balance_due_cents"] = order["provisional_total_cents"] - deposit_paid
    else:
        order["balance_due_cents"] = None


@bp.route("/custom-orders", methods=["POST"])
def create_custom_order():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = get_body()
    customer_id = require_str(body, "customer_id")
    resolve_fk(db.customers, customer_id)
    description = require_str(body, "description")
    estimated_materials = require_int(body, "estimated_materials_cents", gt=0)
    design_fee = require_int(body, "design_fee_cents", ge=0)
    rec = db.new_record()
    rec.update({
        "customer_id": customer_id, "description": description,
        "estimated_materials_cents": estimated_materials, "design_fee_cents": design_fee,
        "provisional_total_cents": None, "deposit_required_cents": None,
        "deposit_paid_cents": 0, "final_total_cents": None, "balance_due_cents": None,
        "line_items": None, "revision_count": 0, "status": "DRAFT",
    })
    db.custom_orders[rec["id"]] = rec
    return success(serialize.custom_order(rec), status=201)


@bp.route("/custom-orders", methods=["GET"])
def list_custom_orders():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Goldsmith", "Customer"})
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    records = [o for o in db.custom_orders.values()
               if customer_id is None or o["customer_id"] == customer_id]
    page, meta = paginate(records, limit, offset)
    return success([serialize.custom_order(r) for r in page], status=200, pagination=meta)


@bp.route("/custom-orders/<oid>", methods=["GET"])
def get_custom_order(oid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Goldsmith", "Customer"})
    rec = resolve_path(db.custom_orders, oid)
    return success(serialize.custom_order(rec), status=200)


def _transition(oid, allowed_roles, from_states, to_state):
    """Shared scaffolding: role, path-existence, state legality, OCC. Returns (rec, body)."""
    _, role = get_caller()
    require_role(role, allowed_roles)
    rec = resolve_path(db.custom_orders, oid)
    body = get_body()
    return rec, body, role


@bp.route("/custom-orders/<oid>/quote", methods=["POST"])
def quote_custom_order(oid):
    rec, body, _ = _transition(oid, {"SalesAssociate"}, ["DRAFT"], "QUOTED")
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Order is not DRAFT")
    require_own_version(rec, body)
    rec["provisional_total_cents"] = provisional_total_cents(
        rec["estimated_materials_cents"], rec["design_fee_cents"])
    rec["deposit_required_cents"] = deposit_required_cents(rec["provisional_total_cents"])
    rec["status"] = "QUOTED"
    recompute_balance(rec)
    db.touch(rec)
    return success(serialize.custom_order(rec), status=200)


@bp.route("/custom-orders/<oid>/start-design", methods=["POST"])
def start_design(oid):
    rec, body, _ = _transition(oid, {"Goldsmith"}, ["DEPOSIT_PAID"], "IN_DESIGN")
    if rec["status"] != "DEPOSIT_PAID":
        raise ApiError("ERR_INVALID_STATE", "Order is not DEPOSIT_PAID")
    require_own_version(rec, body)
    rec["status"] = "IN_DESIGN"
    db.touch(rec)
    return success(serialize.custom_order(rec), status=200)


@bp.route("/custom-orders/<oid>/submit-review", methods=["POST"])
def submit_review(oid):
    rec, body, _ = _transition(oid, {"Goldsmith"}, ["IN_DESIGN"], "DESIGN_REVIEW")
    if rec["status"] != "IN_DESIGN":
        raise ApiError("ERR_INVALID_STATE", "Order is not IN_DESIGN")
    require_own_version(rec, body)
    rec["status"] = "DESIGN_REVIEW"
    db.touch(rec)
    return success(serialize.custom_order(rec), status=200)


@bp.route("/custom-orders/<oid>/request-revision", methods=["POST"])
def request_revision(oid):
    rec, body, _ = _transition(oid, {"SalesAssociate"}, ["DESIGN_REVIEW"], "IN_DESIGN")
    if rec["status"] != "DESIGN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Order is not in DESIGN_REVIEW")
    # Revision cap (state legality already passed) — PRD §3.3.
    if rec["revision_count"] >= MAX_REVISIONS:
        raise ApiError("ERR_MAX_REVISIONS_REACHED", "Maximum revisions reached")
    require_own_version(rec, body)
    rec["revision_count"] += 1
    rec["status"] = "IN_DESIGN"
    db.touch(rec)
    return success(serialize.custom_order(rec), status=200)


@bp.route("/custom-orders/<oid>/approve-design", methods=["POST"])
def approve_design(oid):
    rec, body, _ = _transition(oid, {"SalesAssociate"}, ["DESIGN_REVIEW"], "APPROVED")
    if rec["status"] != "DESIGN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Order is not in DESIGN_REVIEW")
    line_items = body.get("line_items")
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise ApiError("ERR_LINE_ITEMS_REQUIRED", "line_items must be non-empty")
    for li in line_items:
        if not isinstance(li, dict):
            raise ApiError("ERR_INVALID_REQUEST", "line item must be an object")
        if not isinstance(li.get("qty"), int) or isinstance(li.get("qty"), bool):
            raise ApiError("ERR_INVALID_REQUEST", "line item qty must be an integer")
        if not isinstance(li.get("unit_price_cents"), int) or isinstance(li.get("unit_price_cents"), bool):
            raise ApiError("ERR_INVALID_REQUEST", "line item unit_price_cents must be an integer")
        mp = li.get("markup_pct")
        if isinstance(mp, bool) or not isinstance(mp, (int, float)):
            raise ApiError("ERR_INVALID_REQUEST", "line item markup_pct must be a number")
    require_own_version(rec, body)
    rec["line_items"] = line_items
    rec["status"] = "APPROVED"
    db.touch(rec)
    return success(serialize.custom_order(rec), status=200)


@bp.route("/custom-orders/<oid>/start-production", methods=["POST"])
def start_production(oid):
    rec, body, _ = _transition(oid, {"Goldsmith"}, ["APPROVED"], "IN_PRODUCTION")
    if rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Order is not APPROVED")
    require_own_version(rec, body)
    rec["status"] = "IN_PRODUCTION"
    db.touch(rec)
    return success(serialize.custom_order(rec), status=200)


@bp.route("/custom-orders/<oid>/complete-production", methods=["POST"])
def complete_production(oid):
    rec, body, _ = _transition(oid, {"Goldsmith"}, ["IN_PRODUCTION"], "READY")
    if rec["status"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE", "Order is not IN_PRODUCTION")
    require_own_version(rec, body)
    rec["final_total_cents"] = final_total_cents(rec["line_items"], rec["design_fee_cents"])
    rec["status"] = "READY"
    recompute_balance(rec)
    db.touch(rec)
    return success(serialize.custom_order(rec), status=200)


@bp.route("/custom-orders/<oid>/complete", methods=["POST"])
def complete_order(oid):
    rec, body, _ = _transition(oid, {"SalesAssociate"}, ["READY"], "COMPLETED")
    if rec["status"] != "READY":
        raise ApiError("ERR_INVALID_STATE", "Order is not READY")
    if rec["balance_due_cents"] is None or rec["balance_due_cents"] > 0:
        raise ApiError("ERR_BALANCE_OUTSTANDING", "Balance must be cleared")
    require_own_version(rec, body)
    rec["status"] = "COMPLETED"
    db.touch(rec)
    return success(serialize.custom_order(rec), status=200)


@bp.route("/custom-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    rec, body, _ = _transition(oid, {"StoreManager"}, [], "CANCELLED")
    if rec["status"] in ("IN_PRODUCTION", "READY", "COMPLETED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", "Order cannot be cancelled from its current state")
    require_own_version(rec, body)
    rec["status"] = "CANCELLED"
    db.touch(rec)
    # Refund any collected deposit to store credit (PRD §3.3).
    if rec["deposit_paid_cents"] > 0:
        post_ledger_entry(rec["customer_id"], "CREDIT", rec["deposit_paid_cents"], "LAYAWAY_REFUND")
    return success(serialize.custom_order(rec), status=200)
