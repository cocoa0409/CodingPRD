"""Order and Delivery routes."""
from flask import Blueprint, request

import db
from db import stamp_new, touch, _parse_iso
from errors import (err_order_not_found, err_delivery_not_found,
                    err_catalog_item_not_found, err_invalid_request,
                    err_insufficient_permissions,
                    err_order_not_cancellable, err_delivery_not_dispatchable,
                    err_delivery_not_confirmable, err_segregation_of_duties,
                    err_delivery_window_inverted, err_window_outside_port_stay,
                    err_qty_exceeds_remaining, err_customs_clearance_required)
from middleware import require_roles, require_any_authenticated
from response import success_object, success_list, parse_pagination
from services.exposure import recompute_agent_exposure
from services.stock import release_allocations, deduct_confirmed
from services.validate import (get_body, req_string, req_lines_array,
                               req_datetime, qty_at_least_one,
                               qty_at_least_zero)

bp = Blueprint("order_delivery", __name__)


def _order_call(order):
    """Resolve the VesselCall for an order via quotation -> requisition."""
    quotation = db.quotations.get(order.get("quotation_id"))
    if quotation is None:
        return None
    requisition = db.requisitions.get(quotation.get("requisition_id"))
    if requisition is None:
        return None
    return db.vessel_calls.get(requisition.get("vessel_call_id"))


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------

@bp.route("/chandlery/orders/<order_id>", methods=["GET"])
@require_any_authenticated
def get_order(user_id, role, order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise err_order_not_found()
    return success_object(order)


@bp.route("/chandlery/orders/<order_id>/cancel", methods=["POST"])
@require_roles("ChandlerOpsManager")
def cancel_order(user_id, role, order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise err_order_not_found()
    # preconditions: fulfillment OPEN; payment UNINVOICED or INVOICED with
    # zero payments on the invoice (else ERR_ORDER_NOT_CANCELLABLE)
    if order["fulfillment_status"] != "OPEN":
        raise err_order_not_cancellable()
    if order["payment_status"] not in ("UNINVOICED", "INVOICED"):
        raise err_order_not_cancellable()
    if order["payment_status"] == "INVOICED":
        for inv in db.invoices.values():
            if inv["order_id"] == order_id and inv["status"] != "VOID":
                pay_count = sum(1 for p in db.payments.values()
                                if p["invoice_id"] == inv["id"])
                if pay_count > 0:
                    raise err_order_not_cancellable()
    # cascade hop 1 (Order -> Delivery)
    for delivery in db.deliveries.values():
        if delivery["order_id"] == order_id and delivery["status"] in (
                "SCHEDULED", "OUT_FOR_DELIVERY"):
            delivery["status"] = "CANCELLED"
            touch(delivery)
    # cascade hop 1 (Order -> StockLot): release all allocations
    release_allocations(order)
    # cascade hop 2 (Order -> Invoice): unpaid ISSUED invoice -> VOID
    for inv in db.invoices.values():
        if inv["order_id"] == order_id and inv["status"] == "ISSUED":
            pay_count = sum(1 for p in db.payments.values()
                            if p["invoice_id"] == inv["id"])
            if pay_count == 0:
                inv["status"] = "VOID"
                inv["outstanding_cents"] = (inv["total_cents"]
                                            - inv["paid_amount_cents"]
                                            - inv["credited_amount_cents"]
                                            - inv["fx_writeoff_cents"])
                touch(inv)
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    # cascade hop 3 (Invoice -> ShipAgent)
    recompute_agent_exposure(order["agent_id"])
    return success_object(order)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

@bp.route("/chandlery/orders/<order_id>/deliveries", methods=["POST"])
@require_roles("WarehouseSupervisor")
def create_delivery(user_id, role, order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise err_order_not_found()
    body = get_body()
    window_start = req_datetime(body, "window_start")
    window_end = req_datetime(body, "window_end")
    raw_lines = req_lines_array(body, "lines", min_len=1)

    # Validate line shape + FK existence (priorities 3-4). The qty floor
    # (priority 13, ERR_INVALID_QTY) is deliberately NOT checked here yet —
    # it ranks below the customs and temporal gates.
    planned_lines = []
    for line in raw_lines:
        catalog_item_id = line.get("catalog_item_id")
        if not isinstance(catalog_item_id, str) or catalog_item_id.strip() == "":
            raise err_invalid_request("missing or invalid field: catalog_item_id")
        if catalog_item_id not in db.catalog_items:
            raise err_catalog_item_not_found()
        qty = line.get("qty")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise err_invalid_request("qty must be an integer")
        planned_lines.append({"catalog_item_id": catalog_item_id, "qty": qty})

    vessel_call = _order_call(order)

    # priority 7 (business_safety): customs gate — a delivery containing any
    # bonded_eligible line requires customs_clearance_status == CLEARED.
    # Listed before the window rules (priorities 10/11) and the quantity
    # floor/cap (13/14); pinned by test_customs_gate_masks_window_containment.
    for line in planned_lines:
        item = db.catalog_items[line["catalog_item_id"]]
        if item.get("bonded_eligible") and vessel_call["customs_clearance_status"] != "CLEARED":
            raise err_customs_clearance_required()

    # priority 10: window_end strictly after window_start
    if not (window_end > window_start):
        raise err_delivery_window_inverted()

    # priority 11: closed-interval containment within the port stay
    eta = _parse_iso(vessel_call["actual_eta"] or vessel_call["scheduled_eta"])
    etd = _parse_iso(vessel_call["actual_etd"] or vessel_call["scheduled_etd"])
    if window_start < eta or window_end > etd:
        raise err_window_outside_port_stay()

    # priority 13: planned line qty >= 1
    for line in planned_lines:
        qty_at_least_one(line["qty"])

    # priority 14a: quantity cap per line over non-terminal deliveries
    for line in planned_lines:
        item_id = line["catalog_item_id"]
        order_line = next((ol for ol in order["lines"]
                           if ol["catalog_item_id"] == item_id), None)
        if order_line is None:
            # planning a delivery for an item not on the order exceeds remaining
            raise err_qty_exceeds_remaining()
        planned_elsewhere = 0
        for d in db.deliveries.values():
            if d["order_id"] != order_id or d["status"] not in ("SCHEDULED", "OUT_FOR_DELIVERY"):
                continue
            for dl in d["lines"]:
                if dl["catalog_item_id"] == item_id:
                    planned_elsewhere += dl["qty"]
        if planned_elsewhere + order_line["qty_delivered"] + line["qty"] > order_line["qty_ordered"]:
            raise err_qty_exceeds_remaining()

    delivery = {
        "order_id": order_id,
        "window_start": body["window_start"],
        "window_end": body["window_end"],
        "lines": planned_lines,
        "confirmed_lines": None,
        "receiver_name": None,
        "signature_ref": None,
        "confirmed_at": None,
        "created_by_user_id": user_id,
        "status": "SCHEDULED",
    }
    stamp_new(delivery)
    db.deliveries[delivery["id"]] = delivery
    return success_object(delivery, status=201)


@bp.route("/chandlery/orders/<order_id>/deliveries", methods=["GET"])
@require_any_authenticated
def list_deliveries(user_id, role, order_id):
    if order_id not in db.orders:
        raise err_order_not_found()
    items = [d for d in db.deliveries.values() if d["order_id"] == order_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))


@bp.route("/chandlery/deliveries/<delivery_id>", methods=["GET"])
@require_any_authenticated
def get_delivery(user_id, role, delivery_id):
    d = db.deliveries.get(delivery_id)
    if d is None:
        raise err_delivery_not_found()
    return success_object(d)


@bp.route("/chandlery/deliveries/<delivery_id>/dispatch", methods=["POST"])
@require_roles("WarehouseSupervisor")
def dispatch_delivery(user_id, role, delivery_id):
    d = db.deliveries.get(delivery_id)
    if d is None:
        raise err_delivery_not_found()
    if d["status"] != "SCHEDULED":
        raise err_delivery_not_dispatchable()
    d["status"] = "OUT_FOR_DELIVERY"
    touch(d)
    return success_object(d)


@bp.route("/chandlery/deliveries/<delivery_id>/confirm", methods=["POST"])
@require_roles("VesselCateringOfficer")
def confirm_delivery(user_id, role, delivery_id):
    d = db.deliveries.get(delivery_id)
    if d is None:
        raise err_delivery_not_found()
    body = get_body()
    receiver_name = req_string(body, "receiver_name")
    signature_ref = req_string(body, "signature_ref")
    raw_confirmed = body.get("confirmed_lines")
    if not isinstance(raw_confirmed, list) or len(raw_confirmed) < 1:
        raise err_invalid_request("confirmed_lines must be a non-empty array")
    confirmed_lines = []
    for line in raw_confirmed:
        if not isinstance(line, dict):
            raise err_invalid_request("each confirmed line must be an object")
        catalog_item_id = line.get("catalog_item_id")
        if not isinstance(catalog_item_id, str) or catalog_item_id.strip() == "":
            raise err_invalid_request("missing or invalid field: catalog_item_id")
        qty = line.get("qty")
        qty_at_least_zero(qty)
        confirmed_lines.append({"catalog_item_id": catalog_item_id, "qty": qty})

    # state: delivery must be OUT_FOR_DELIVERY
    if d["status"] != "OUT_FOR_DELIVERY":
        raise err_delivery_not_confirmable()
    order = db.orders[d["order_id"]]
    vessel_call = _order_call(order)
    # ownership: acting officer must own the underlying vessel call
    if vessel_call is None or user_id != vessel_call["id"]:
        raise err_insufficient_permissions()
    # segregation of duties: confirmer != creator
    if user_id == d["created_by_user_id"]:
        raise err_segregation_of_duties()
    # each confirmed line qty <= planned qty on this delivery
    for cl in confirmed_lines:
        planned = next((pl for pl in d["lines"]
                        if pl["catalog_item_id"] == cl["catalog_item_id"]), None)
        if planned is None or cl["qty"] > planned["qty"]:
            raise err_qty_exceeds_remaining()

    # commit
    d["confirmed_lines"] = confirmed_lines
    d["receiver_name"] = receiver_name
    d["signature_ref"] = signature_ref
    d["confirmed_at"] = db.now_iso()
    d["status"] = "DELIVERED"
    touch(d)

    # cascade hop 1 (Delivery -> Order): qty_delivered accumulates; re-derive
    # fulfillment. hop 1b (Delivery -> StockLot): reserved -= confirmed,
    # on_hand -= confirmed per allocated lot.
    for cl in confirmed_lines:
        order_line = next((ol for ol in order["lines"]
                           if ol["catalog_item_id"] == cl["catalog_item_id"]), None)
        if order_line is None:
            continue
        order_line["qty_delivered"] += cl["qty"]
        deduct_confirmed(order_line, cl["qty"])
    all_filled = all(ol["qty_delivered"] >= ol["qty_ordered"] for ol in order["lines"])
    if all_filled:
        order["fulfillment_status"] = "DELIVERED"
        # release reservation remainder (none when fully delivered)
    else:
        order["fulfillment_status"] = "PARTIALLY_DELIVERED"
    touch(order)
    # totals frozen -> agent exposure unaffected by delivery activity
    return success_object(d)
