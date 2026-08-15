"""Quality claims: file, list, get, approve (chargeback cascade), reject."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import new_id, public, stamp_new, store, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    body_json,
    get_or_404,
    paginate,
    require_roles,
    sorted_created,
)
from response import success_list, success_object
from services.domain import (
    SUSPENSION_THRESHOLD_CENTS,
    claim_window_open,
    compute_chargeback,
    suspend_factory_cascade,
)

bp = Blueprint("claims", __name__)


def _get_claim(claimId):
    return get_or_404(
        store.claims, claimId, "ERR_QUALITY_CLAIM_NOT_FOUND", "QualityClaim"
    )


def _validate_items(data):
    items = data.get("items")
    if not isinstance(items, list) or len(items) == 0:
        raise ApiError("ERR_VALIDATION", "items must be a non-empty array", 400)
    for item in items:
        if not isinstance(item, dict):
            raise ApiError("ERR_VALIDATION", "each claim item must be an object", 400)
        description = item.get("description")
        if not isinstance(description, str):
            raise ApiError(
                "ERR_VALIDATION", "claim item description must be a string", 400
            )
        qty = item.get("qty_defective")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise ApiError(
                "ERR_VALIDATION", "claim item qty_defective must be an integer >= 1",
                400,
            )
        price = item.get("unit_price_cents")
        if not isinstance(price, int) or isinstance(price, bool) or price < 1:
            raise ApiError(
                "ERR_VALIDATION",
                "claim item unit_price_cents must be an integer >= 1",
                400,
            )
    return [
        {
            "description": item["description"],
            "qty_defective": item["qty_defective"],
            "unit_price_cents": item["unit_price_cents"],
        }
        for item in items
    ]


@bp.route("/sourcing/purchase-orders/<poId>/quality-claims", methods=["POST"])
def file_claim(poId):
    uid, _ = require_roles("BuyerManager")
    po = get_or_404(
        store.purchase_orders, poId, "ERR_PURCHASE_ORDER_NOT_FOUND", "PurchaseOrder"
    )
    data = body_json()
    items = _validate_items(data)
    if po["buyer_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller does not own the purchase order",
            403,
        )
    if not claim_window_open(po["id"]):
        raise ApiError(
            "ERR_CLAIM_WINDOW_CLOSED",
            "The claim window (latest delivery + 30 days) is closed or no "
            "delivery has occurred",
            409,
        )
    base_amount = sum(i["qty_defective"] * i["unit_price_cents"] for i in items)
    defective_qty = sum(i["qty_defective"] for i in items)
    defect_rate = (Decimal(defective_qty) / Decimal(po["ordered_qty"])).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    claim = stamp_new(
        {
            "id": new_id(),
            "po_id": po["id"],
            "filed_by_buyer_id": uid,
            "items": items,
            "base_amount_cents": base_amount,
            "defective_qty": defective_qty,
            "defect_rate": float(defect_rate),
            "penalty_cents": 0,
            "total_chargeback_cents": 0,
            "approved_by_agent_id": None,
            "status": "FILED",
        }
    )
    store.claims[claim["id"]] = claim
    return success_object(public(claim), 201)


@bp.route("/sourcing/quality-claims", methods=["GET"])
def list_claims():
    require_roles(*ALL_ROLES)
    items = list(store.claims.values())
    po_id = request.args.get("po_id")
    filed_by = request.args.get("filed_by_buyer_id")
    approved_by = request.args.get("approved_by_agent_id")
    status = request.args.get("status")
    if po_id is not None:
        items = [c for c in items if c["po_id"] == po_id]
    if filed_by is not None:
        items = [c for c in items if c["filed_by_buyer_id"] == filed_by]
    if approved_by is not None:
        items = [c for c in items if c["approved_by_agent_id"] == approved_by]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([public(c) for c in page], limit, offset, total)


@bp.route("/sourcing/quality-claims/<claimId>", methods=["GET"])
def get_claim(claimId):
    require_roles(*ALL_ROLES)
    return success_object(public(_get_claim(claimId)))


def _check_adjudicator(claim, uid):
    if claim["status"] != "FILED":
        raise ApiError("ERR_CLAIM_NOT_REVIEWABLE", "QualityClaim is not FILED", 409)
    po = store.purchase_orders.get(claim["po_id"])
    if po is not None and po["assigned_agent_id"] == uid:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The PO's assigned agent cannot adjudicate claims against it",
            403,
        )
    return po


@bp.route("/sourcing/quality-claims/<claimId>/approve", methods=["POST"])
def approve_claim(claimId):
    uid, _ = require_roles("SourcingAgent")
    claim = _get_claim(claimId)
    po = _check_adjudicator(claim, uid)
    base_amount, defective_qty, defect_rate, penalty, total = compute_chargeback(
        claim, po
    )
    if total > po["remaining_payable_cents"]:
        raise ApiError(
            "ERR_CLAIM_EXCEEDS_PAYABLE",
            "Computed chargeback exceeds the PO's remaining payable balance",
            422,
        )
    claim["status"] = "APPROVED"
    claim["base_amount_cents"] = base_amount
    claim["defective_qty"] = defective_qty
    claim["defect_rate"] = float(defect_rate)
    claim["penalty_cents"] = penalty
    claim["total_chargeback_cents"] = total
    claim["approved_by_agent_id"] = uid
    touch(claim)
    po["remaining_payable_cents"] -= total
    touch(po)
    factory = store.factories.get(po["factory_id"])
    if factory is not None:
        factory["debit_balance_cents"] += total
        touch(factory)
    buyer = store.buyers.get(po["buyer_id"])
    if buyer is not None:
        buyer["credit_balance_cents"] += total
        touch(buyer)
    if (
        factory is not None
        and factory["debit_balance_cents"] >= SUSPENSION_THRESHOLD_CENTS
        and factory["status"] == "ACTIVE"
    ):
        suspend_factory_cascade(factory)
    return success_object(public(claim))


@bp.route("/sourcing/quality-claims/<claimId>/reject", methods=["POST"])
def reject_claim(claimId):
    uid, _ = require_roles("SourcingAgent")
    claim = _get_claim(claimId)
    _check_adjudicator(claim, uid)
    claim["status"] = "REJECTED"
    touch(claim)
    return success_object(public(claim))
