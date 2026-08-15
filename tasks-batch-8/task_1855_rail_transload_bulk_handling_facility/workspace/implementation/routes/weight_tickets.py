"""Weight ticket endpoints: create (DRAFT, net computed), get, list, certify
(the moment money and material move), void (exact compensation)."""

from flask import Blueprint, request

import domain
from db import STORE, new_entity, touch, public
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SCALE_TOLERANCE,
    ERR_PAYLOAD_EXCEEDED, ERR_OVER_DELIVERY,
)
from middleware import auth_context, require_role, require_ownership, ALL_ROLES
from response import ok, paginated
from util import dec, round3, tons_add, tons_sub
from validate import body, req_str, req_pos_num

bp = Blueprint("weight_tickets", __name__)


def _get_ticket_or_404(weight_ticket_id):
    ticket = STORE.weight_tickets.get(weight_ticket_id)
    if ticket is None:
        raise_err(ERR_NOT_FOUND, "weight ticket id does not exist")
    return ticket


def _ticket_customer_id(ticket):
    return STORE.railcars[ticket["railcar_id"]]["customer_id"]


@bp.route("/transload/transfer-orders/<tid>/weight-tickets", methods=["POST"])
def create_weight_ticket(tid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    # Priority 3: path ids resolve.
    order = STORE.transfer_orders.get(tid)
    if order is None:
        raise_err(ERR_NOT_FOUND, "transfer order id does not exist")
    data = body()
    truck_reference = req_str(data, "truck_reference")
    gross = round3(req_pos_num(data, "gross_weight_tons"))
    tare = round3(req_pos_num(data, "tare_weight_tons"))
    max_payload = round3(req_pos_num(data, "truck_max_payload_tons"))
    net = round3(dec(gross) - dec(tare))
    ticket = new_entity(STORE.weight_tickets, {
        "transfer_order_id": order["id"],
        "railcar_id": order["railcar_id"],
        "truck_reference": truck_reference,
        "gross_weight_tons": gross,
        "tare_weight_tons": tare,
        "truck_max_payload_tons": max_payload,
        "net_weight_tons": net,
        "status": "DRAFT",
    })
    return ok(public(ticket), status=201)


@bp.route("/transload/weight-tickets/<wid>", methods=["GET"])
def get_weight_ticket(wid):
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    ticket = _get_ticket_or_404(wid)
    require_ownership(user_id, role, _ticket_customer_id(ticket))
    return ok(public(ticket))


@bp.route("/transload/weight-tickets", methods=["GET"])
def list_weight_tickets():
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    transfer_order_id = request.args.get("transfer_order_id")
    railcar_id = request.args.get("railcar_id")
    status = request.args.get("status")
    items = sorted(STORE.weight_tickets.values(), key=lambda t: (t["created_at"], t["_seq"]))
    if role == "CustomerRep":
        items = [t for t in items if _ticket_customer_id(t) == user_id]
    if transfer_order_id is not None:
        items = [t for t in items if t["transfer_order_id"] == transfer_order_id]
    if railcar_id is not None:
        items = [t for t in items if t["railcar_id"] == railcar_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, meta = paginated(items)
    return ok([public(t) for t in page], pagination=meta)


@bp.route("/transload/weight-tickets/<wid>/certify", methods=["POST"])
def certify_weight_ticket(wid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    ticket = _get_ticket_or_404(wid)
    # Priority 5: state -- ticket DRAFT and parent order ACTIVE.
    if ticket["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "weight ticket is not DRAFT")
    order = STORE.transfer_orders[ticket["transfer_order_id"]]
    if order["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "transfer order is not ACTIVE")
    # Priority 11: scale/payload/over-delivery gates, in order.
    if not dec(ticket["tare_weight_tons"]) < dec(ticket["gross_weight_tons"]):
        raise_err(ERR_SCALE_TOLERANCE, "tare weight must be strictly less than gross weight")
    net = dec(ticket["net_weight_tons"])
    if net > dec(ticket["truck_max_payload_tons"]):
        raise_err(ERR_PAYLOAD_EXCEEDED, "net weight exceeds the truck's payload limit")
    if dec(order["quantity_completed_tons"]) + net > dec(order["quantity_planned_tons"]):
        raise_err(ERR_OVER_DELIVERY, "certification would exceed the planned quantity")
    car = STORE.railcars[ticket["railcar_id"]]
    if dec(car["quantity_remaining_tons"]) < net:
        raise_err(ERR_OVER_DELIVERY, "certification would exceed the car's remaining quantity")
    # Three quantity ledgers move together.
    order["quantity_completed_tons"] = tons_add(order["quantity_completed_tons"], ticket["net_weight_tons"])
    touch(order)
    car["quantity_remaining_tons"] = tons_sub(car["quantity_remaining_tons"], ticket["net_weight_tons"])
    touch(car)
    lot = STORE.lots[car["lot_id"]]
    lot["quantity_shipped_tons"] = tons_add(lot["quantity_shipped_tons"], ticket["net_weight_tons"])
    touch(lot)
    ticket["status"] = "CERTIFIED"
    touch(ticket)
    # Cascade 1: a car emptied mid-transfer advances toward cleaning/release.
    domain.car_empty_cascade(car)
    # Cascade 2: reaching the planned quantity auto-completes the order.
    if (dec(order["quantity_completed_tons"]) >= dec(order["quantity_planned_tons"])
            and order["status"] == "ACTIVE"):
        domain.complete_transfer_order(order, release_equipment=True)
    return ok(public(ticket))


@bp.route("/transload/weight-tickets/<wid>/void", methods=["POST"])
def void_weight_ticket(wid):
    _, role = auth_context()
    require_role(role, ["TransferOperator"])
    ticket = _get_ticket_or_404(wid)
    # Priority 5: state -- ticket CERTIFIED and parent order ACTIVE/PAUSED.
    if ticket["status"] != "CERTIFIED":
        raise_err(ERR_INVALID_STATE, "weight ticket is not CERTIFIED")
    order = STORE.transfer_orders[ticket["transfer_order_id"]]
    if order["status"] not in ("ACTIVE", "PAUSED"):
        raise_err(ERR_INVALID_STATE, "transfer order is not ACTIVE or PAUSED")
    # Compensation: certify + void restores all three quantities exactly.
    order["quantity_completed_tons"] = tons_sub(order["quantity_completed_tons"], ticket["net_weight_tons"])
    touch(order)
    car = STORE.railcars[ticket["railcar_id"]]
    car["quantity_remaining_tons"] = tons_add(car["quantity_remaining_tons"], ticket["net_weight_tons"])
    touch(car)
    lot = STORE.lots[car["lot_id"]]
    lot["quantity_shipped_tons"] = tons_sub(lot["quantity_shipped_tons"], ticket["net_weight_tons"])
    touch(lot)
    ticket["status"] = "VOIDED"
    touch(ticket)
    return ok(public(ticket))
