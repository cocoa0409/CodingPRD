"""Purchase orders: list, get, amend (OCC), cancel, milestone plan creation."""

from flask import Blueprint, request

from db import new_id, public, stamp_new, store, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    body_json,
    get_or_404,
    paginate,
    req_int,
    req_str,
    require_roles,
    sorted_created,
    DELIVERY_MONTH_RE,
)
from response import success_list, success_object
from services.domain import (
    committed_units,
    compute_commission,
    recompute_remaining_payable,
)

bp = Blueprint("purchase_orders", __name__)

PO_AMENDABLE_STATES = ("ACTIVE", "PARTIALLY_SHIPPED")


def _get_po(poId):
    return get_or_404(
        store.purchase_orders, poId, "ERR_PURCHASE_ORDER_NOT_FOUND", "PurchaseOrder"
    )


@bp.route("/sourcing/purchase-orders", methods=["GET"])
def list_purchase_orders():
    require_roles(*ALL_ROLES)
    items = list(store.purchase_orders.values())
    filters = (
        ("buyer_id", "buyer_id"),
        ("factory_id", "factory_id"),
        ("quotation_id", "quotation_id"),
        ("sourcing_request_id", "sourcing_request_id"),
        ("assigned_agent_id", "assigned_agent_id"),
        ("status", "status"),
        ("delivery_month", "delivery_month"),
    )
    for param, field in filters:
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p[field] == value]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([public(p) for p in page], limit, offset, total)


@bp.route("/sourcing/purchase-orders/<poId>", methods=["GET"])
def get_purchase_order(poId):
    require_roles(*ALL_ROLES)
    return success_object(public(_get_po(poId)))


@bp.route("/sourcing/purchase-orders/<poId>/amend", methods=["POST"])
def amend_purchase_order(poId):
    uid, _ = require_roles("SourcingAgent")
    po = _get_po(poId)
    data = body_json()
    if po["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this purchase order",
            403,
        )
    if po["status"] not in PO_AMENDABLE_STATES:
        raise ApiError(
            "ERR_PO_NOT_ACTIVE",
            "PurchaseOrder is not ACTIVE or PARTIALLY_SHIPPED",
            409,
        )
    expected = data.get("expected_po_version")
    if expected is None:
        raise ApiError(
            "ERR_VALIDATION", "Missing required field: expected_po_version", 400
        )
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(
            "ERR_VALIDATION", "expected_po_version must be an integer", 400
        )
    if expected != po["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_po_version does not match the current version",
            412,
        )
    new_price = data.get("unit_price_cents")
    new_qty = data.get("ordered_qty")
    new_month = data.get("delivery_month")
    if new_price is None and new_qty is None and new_month is None:
        raise ApiError(
            "ERR_VALIDATION",
            "Amend requires at least one of unit_price_cents, ordered_qty, "
            "delivery_month",
            400,
        )
    if new_price is not None and (
        not isinstance(new_price, int) or isinstance(new_price, bool)
    ):
        raise ApiError("ERR_VALIDATION", "unit_price_cents must be an integer", 400)
    if new_qty is not None and (
        not isinstance(new_qty, int) or isinstance(new_qty, bool)
    ):
        raise ApiError("ERR_VALIDATION", "ordered_qty must be an integer", 400)
    if new_month is not None and (
        not isinstance(new_month, str) or not DELIVERY_MONTH_RE.match(new_month)
    ):
        raise ApiError(
            "ERR_VALIDATION", "delivery_month must be a YYYY-MM string", 400
        )
    eff_price = po["unit_price_cents"] if new_price is None else new_price
    eff_qty = po["ordered_qty"] if new_qty is None else new_qty
    eff_month = po["delivery_month"] if new_month is None else new_month
    if eff_qty < po["shipped_qty"] + po["cancelled_qty"]:
        raise ApiError(
            "ERR_AMEND_BELOW_SHIPPED",
            "Amended ordered_qty is below shipped_qty + cancelled_qty",
            422,
        )
    qty_or_month_changed = (new_qty is not None and new_qty != po["ordered_qty"]) or (
        new_month is not None and new_month != po["delivery_month"]
    )
    if qty_or_month_changed:
        factory = store.factories.get(po["factory_id"])
        capacity = factory["monthly_capacity_units"] if factory else None
        if capacity is not None:
            candidate = eff_qty - po["cancelled_qty"]
            others = committed_units(factory["id"], eff_month, exclude_po_id=po["id"])
            if others + candidate > capacity:
                raise ApiError(
                    "ERR_CAPACITY_EXCEEDED",
                    "Capacity ceiling exceeded for the delivery month",
                    422,
                )
    po["unit_price_cents"] = eff_price
    po["ordered_qty"] = eff_qty
    po["delivery_month"] = eff_month
    po["total_cents"] = eff_qty * eff_price
    po["open_qty"] = eff_qty - po["shipped_qty"] - po["cancelled_qty"]
    sr = store.sourcing_requests.get(po["sourcing_request_id"])
    if sr is not None:
        commission, rate_bp = compute_commission(po, sr)
        po["provisional_commission_cents"] = commission
        po["commission_rate_bp"] = rate_bp
    recompute_remaining_payable(po)
    touch(po)
    return success_object(public(po))


@bp.route("/sourcing/purchase-orders/<poId>/cancel", methods=["POST"])
def cancel_purchase_order(poId):
    uid, _ = require_roles("SourcingAgent")
    po = _get_po(poId)
    if po["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this purchase order",
            403,
        )
    if po["status"] not in PO_AMENDABLE_STATES:
        raise ApiError(
            "ERR_PO_NOT_ACTIVE",
            "PurchaseOrder is not ACTIVE or PARTIALLY_SHIPPED",
            409,
        )
    po["status"] = "CANCELLED"
    po["cancelled_qty"] += po["open_qty"]
    po["open_qty"] = 0
    touch(po)
    return success_object(public(po))


@bp.route("/sourcing/purchase-orders/<poId>/milestones", methods=["POST"])
def create_milestone(poId):
    uid, _ = require_roles("SourcingAgent")
    po = _get_po(poId)
    data = body_json()
    name = req_str(data, "name")
    weight_pct = req_int(data, "weight_pct", lo=1, hi=100)
    if po["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this purchase order",
            403,
        )
    if po["status"] != "ACTIVE":
        raise ApiError("ERR_PO_NOT_ACTIVE", "PurchaseOrder is not ACTIVE", 409)
    if po["milestone_plan_locked"]:
        raise ApiError(
            "ERR_MILESTONE_PLAN_LOCKED",
            "Milestone plan is already locked (weights sum to 100)",
            409,
        )
    existing_total = sum(
        m["weight_pct"] for m in store.milestones.values() if m["po_id"] == po["id"]
    )
    if existing_total + weight_pct > 100:
        raise ApiError(
            "ERR_INVALID_WEIGHT_TOTAL",
            "Milestone weight would push the cumulative total above 100",
            409,
        )
    milestone = stamp_new(
        {
            "id": new_id(),
            "po_id": po["id"],
            "name": name,
            "weight_pct": weight_pct,
            "evidence_note": None,
            "status": "PLANNED",
        }
    )
    store.milestones[milestone["id"]] = milestone
    if existing_total + weight_pct == 100:
        po["milestone_plan_locked"] = True
        touch(po)
    return success_object(public(milestone), 201)
