"""Shipments: book, list, get, handover-documents, confirm-receipt, cancel."""

from flask import Blueprint, request

from db import new_id, now_iso, public, stamp_new, store, touch
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
)
from response import success_list, success_object
from services.domain import close_po_if_complete, live_shipments

bp = Blueprint("shipments", __name__)


def _get_shipment(shipmentId):
    return get_or_404(
        store.shipments, shipmentId, "ERR_SHIPMENT_NOT_FOUND", "Shipment"
    )


@bp.route("/sourcing/purchase-orders/<poId>/shipments", methods=["POST"])
def book_shipment(poId):
    uid, _ = require_roles("SourcingAgent")
    po = get_or_404(
        store.purchase_orders, poId, "ERR_PURCHASE_ORDER_NOT_FOUND", "PurchaseOrder"
    )
    data = body_json()
    shipped_qty_raw = data.get("shipped_qty")
    if not isinstance(shipped_qty_raw, int) or isinstance(shipped_qty_raw, bool):
        raise ApiError(
            "ERR_VALIDATION", "Missing or invalid required field: shipped_qty", 400
        )
    vessel_ref = req_str(data, "vessel_ref")
    if po["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this purchase order",
            403,
        )
    if po["status"] not in ("ACTIVE", "PARTIALLY_SHIPPED"):
        raise ApiError(
            "ERR_PO_NOT_ACTIVE",
            "PurchaseOrder is not ACTIVE or PARTIALLY_SHIPPED",
            409,
        )
    factory = store.factories.get(po["factory_id"])
    if factory is not None and factory["status"] != "ACTIVE":
        raise ApiError("ERR_FACTORY_SUSPENDED", "Factory is SUSPENDED", 409)
    if po["ship_blocked"]:
        raise ApiError(
            "ERR_FACTORY_NOT_COMPLIANT",
            "Factory compliance posture blocks this purchase order",
            409,
        )
    if po["production_status"] != "PRODUCTION_COMPLETE":
        raise ApiError(
            "ERR_PO_NOT_READY_FOR_PSI",
            "Shipment booking requires production_status PRODUCTION_COMPLETE",
            409,
        )
    if po["latest_psi_result"] != "PASSED":
        raise ApiError(
            "ERR_NO_PASSING_PSI",
            "Shipment booking requires a PASSED PSI result",
            409,
        )
    if shipped_qty_raw < 1 or shipped_qty_raw > po["open_qty"]:
        raise ApiError(
            "ERR_SHIP_QTY_INVALID",
            "shipped_qty must be between 1 and the PO's open_qty",
            422,
        )
    shipment = stamp_new(
        {
            "id": new_id(),
            "po_id": po["id"],
            "shipped_qty": shipped_qty_raw,
            "vessel_ref": vessel_ref,
            "doc_refs": [],
            "delivered_at": None,
            "status": "BOOKED",
            "_delivered_dt": None,
        }
    )
    store.shipments[shipment["id"]] = shipment
    po["shipped_qty"] += shipped_qty_raw
    po["open_qty"] = po["ordered_qty"] - po["shipped_qty"] - po["cancelled_qty"]
    if po["open_qty"] == 0:
        po["status"] = "SHIPPED"
    elif po["status"] == "ACTIVE":
        po["status"] = "PARTIALLY_SHIPPED"
    touch(po)
    return success_object(public(shipment), 201)


@bp.route("/sourcing/shipments", methods=["GET"])
def list_shipments():
    require_roles(*ALL_ROLES)
    items = list(store.shipments.values())
    po_id = request.args.get("po_id")
    status = request.args.get("status")
    if po_id is not None:
        items = [s for s in items if s["po_id"] == po_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([public(s) for s in page], limit, offset, total)


@bp.route("/sourcing/shipments/<shipmentId>", methods=["GET"])
def get_shipment(shipmentId):
    require_roles(*ALL_ROLES)
    return success_object(public(_get_shipment(shipmentId)))


@bp.route("/sourcing/shipments/<shipmentId>/handover-documents", methods=["POST"])
def handover_documents(shipmentId):
    uid, _ = require_roles("FactoryRep")
    shipment = _get_shipment(shipmentId)
    data = body_json()
    doc_refs = data.get("doc_refs")
    if (
        not isinstance(doc_refs, list)
        or len(doc_refs) == 0
        or any(not isinstance(d, str) for d in doc_refs)
    ):
        raise ApiError(
            "ERR_VALIDATION", "doc_refs must be a non-empty array of strings", 400
        )
    po = store.purchase_orders.get(shipment["po_id"])
    if po is None or po["factory_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller does not belong to the purchase order's factory",
            403,
        )
    if shipment["status"] != "BOOKED":
        raise ApiError(
            "ERR_SHIPMENT_STATE_INVALID", "Shipment is not BOOKED", 409
        )
    shipment["status"] = "DOCS_HANDED_OVER"
    shipment["doc_refs"] = doc_refs
    touch(shipment)
    if po["document_status"] != "HANDED_OVER":
        po["document_status"] = "HANDED_OVER"
        touch(po)
    return success_object(public(shipment))


@bp.route("/sourcing/shipments/<shipmentId>/confirm-receipt", methods=["POST"])
def confirm_receipt(shipmentId):
    uid, _ = require_roles("BuyerManager")
    shipment = _get_shipment(shipmentId)
    po = store.purchase_orders.get(shipment["po_id"])
    if po is None or po["buyer_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller does not own the purchase order",
            403,
        )
    if shipment["status"] != "DOCS_HANDED_OVER":
        raise ApiError(
            "ERR_SHIPMENT_STATE_INVALID", "Shipment is not DOCS_HANDED_OVER", 409
        )
    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = now_iso()
    shipment["_delivered_dt"] = store.clock
    touch(shipment)
    close_po_if_complete(po)
    return success_object(public(shipment))


@bp.route("/sourcing/shipments/<shipmentId>/cancel", methods=["POST"])
def cancel_shipment(shipmentId):
    uid, _ = require_roles("SourcingAgent")
    shipment = _get_shipment(shipmentId)
    po = store.purchase_orders.get(shipment["po_id"])
    if po is None or po["assigned_agent_id"] != uid:
        raise ApiError(
            "ERR_OWNERSHIP_SCOPE_VIOLATION",
            "Caller is not the assigned agent for this purchase order",
            403,
        )
    if shipment["status"] != "BOOKED":
        raise ApiError(
            "ERR_SHIPMENT_STATE_INVALID", "Shipment is not BOOKED", 409
        )
    shipment["status"] = "CANCELLED"
    touch(shipment)
    po["shipped_qty"] -= shipment["shipped_qty"]
    po["open_qty"] = po["ordered_qty"] - po["shipped_qty"] - po["cancelled_qty"]
    if po["status"] in ("PARTIALLY_SHIPPED", "SHIPPED"):
        live = live_shipments(po["id"])
        if not live:
            po["status"] = "ACTIVE"
        elif po["open_qty"] > 0:
            po["status"] = "PARTIALLY_SHIPPED"
        else:
            po["status"] = "SHIPPED"
    touch(po)
    return success_object(public(shipment))
